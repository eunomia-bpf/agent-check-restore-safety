# Independent semantic review: `PlanInvariant.lean`

Date: 2026-08-01 (America/Vancouver)

Reviewed source SHA-256:
`b0f6f2dc48de118604765a5e4d03cda4423e3f7b17e0ef4bc4bd7a75e1161f02`
(1,083 lines, 46,656 bytes).

## Verdict

**MIXED overall.**  The frozen artifact is a **PASS for the isolated,
Prepare-only multi-slot invariant gate**:

> From source `LWF`, source `AC`, the current `PlanData.Valid`, a nonempty
> remaining batch, a successful Boolean version comparison, and a successful
> finite assignment check, the controller computes the first nonempty
> `(slot, owner)` group, constructs the repository's real `PrepareOK`, takes
> exactly `Step.core (CoreStep.prepare ...)` to the exact `prepareState`,
> increments the version, updates exposure by the actual promoted demand,
> preserves every field of this module's `Valid`, and preserves `LWF` and
> `AC`.  Every finite trace consisting only of these edges preserves the same
> properties, and every edge strictly decreases the remaining-claim
> cardinality.

It is **not yet a PASS for the frozen experiment's complete authority-plan or
full-history headline**.  This `PlanData.Valid` has only
`B_i + E_i <= P_i`; it has no `W_i`, no discrete remaining/prepared/withdrawn
leaf ledger, and no exact `B_i + E_i + W_i = P_i`.  Its RTC contains only
`PreparePlanned` edges, not canonical Fork/Restore, restriction/Revoke,
same-slot Merge, checkpoint, or ticket edges.  Finally, `two_prepare_gate` is a
sound conditional composition theorem but the module contains no closed
finite instance proving that its two assignment/nonempty premises are jointly
inhabited.  These limits prevent the stronger phrases "complete residual
invariant," "arbitrary admitted agent histories," and "nonvacuous two-step
fixture" from being attributed to this file.

## Gate-by-gate audit

| Gate | Result | Semantic finding |
|---|---|---|
| Computed `firstGroup` | **PASS** | `activeGroups` enumerates all finite `(slot, owner)` pairs and keeps exactly nonempty groups; `firstGroup` takes their lexicographic minimum.  `headGroup` is then a function of the current lifecycle, `remaining`, and `rootSlot`.  No caller supplies a slot, owner, group, or cursor.  Selection is by `Finset.Nonempty`, so a zero-demand claim remains schedulable and is not erased by vector arithmetic. |
| Nonempty remaining implies an executable head exists | **PASS** | `firstGroup_exists_of_remaining` derives a concrete head from `Valid.remaining_rooted`; `headGroup_nonempty_of_firstGroup` derives the real nonempty claim group. |
| Source-only plan premises; no target oracle | **PASS** | `PreparePlanned.mk` accepts source `LWF`, source `Valid`, source remaining nonemptiness, `checkVersion ... = true`, and `Plan.checkAssignment ... = true`.  It accepts no target `Valid`, target `LWF`/`AC`, `PrepareOK`, target readiness, `hPfits`, `hbatchP`, proposed target batch, or proposed target cursor.  The occurrences named `hTarget` inside cursor proofs are equalities exposing the *computed* target `firstGroup`, not target certificates. |
| Structural phase invariant | **PASS** | `HeadPhaseBound` is not a field of `Valid`.  `Valid.derived_head_phase_bound` derives it: before the head, `BatchBound` implies `E <= P`; after the head, `CursorPhase` gives `E = 0`; outside `slots`, `E_outside_zero` applies.  `CursorPhase` is still a load-bearing source invariant and must remain explicit in prose. |
| Readiness is derived, not renamed | **PASS** | `current_group_promotedLoad_le_capacity` combines the exact durable equation, the derived phase bound, the live-load envelope, `headGroup <= L`, the deadline, and capacity equality.  There is no per-edge capacity or readiness premise.  This is a global schedule certificate deriving the local check; it does not eliminate the need for the source envelope/deadline invariants. |
| Actual assignment checker and `PrepareOK` | **PASS** | `current_group_prepare_ok` uses `Plan.checkAssignment_sound` for `assigned_mem`, coverage, injectivity, and freshness.  Tentative/open/grant fields come from the computed group plus source `LWF`; `base` comes from the schedule proof.  No `PrepareOK` is supplied. |
| Exact `prepareState` and actual `Step` projection | **PASS** | `advancePrepare.lifecycle` is definitionally `prepareState` on the computed head.  `current_group_actual_step` constructs `Step.core (CoreStep.prepare ...)`, and `PreparePlanned.actual_step` projects to that exact state.  This is not a shadow list rewrite. |
| Exposure and durable-load update | **PASS** | `prepareState_headGroup_durableLoad` proves the actual durable delta is exactly the head-group batch load.  `afterPrepareGroup_totalE` adds exactly the same quantity to the source head slot; `afterPrepareGroup_preserves_durableEq` reconnects this to the real target durable load.  Cleanup can only remove additional tentative claims and does not alter that durable row. |
| Every field of this module's `Valid` is preserved | **PASS, locally scoped** | `afterPrepareGroup_preserves_valid` constructs all eleven target fields: capacity, remaining rootedness, owner/root purity, root membership, outside-zero facts, durable equality, live envelope, deadline, batch bound, and cursor phase.  Target `Valid` is a conclusion.  This is not the frozen experiment's full typed invariant because `W` and the discrete leaf partition are absent and `BatchBound` is only an inequality. |
| `LWF` and `AC` preservation | **PASS** | Given source `AC`, `PreparePlanned.preserves_wf_ac` applies the repository's exact `prepare_preserves_wf_ac`; neither target property is assumed.  The theorem intentionally says nothing about physical external effects or exactly-once execution. |
| Version comparison / abstract CAS | **PASS at the sequential specification level; not a runtime-CAS proof** | `checkVersion` is executable `decide (offered = version)`, `version_sound` derives equality from a successful Boolean check, and the same `PreparePlanned` rule installs the computed target with `version + 1`.  Thus the abstract successful check-and-update is one transition.  There is no concurrent store, interleaving, failed/stale request trace, durability model, or SQLite linearizability theorem.  Moreover, `PlannedPrepareEdge` existentially hides `offered`, so trace preservation studies successful edges rather than rejection behavior. |
| Arbitrary finite Prepare-only RTC | **PASS for preservation; MIXED for nonvacuity** | `planned_prepare_trace_preserves` inducts over an actual `ReflTransGen PlannedPrepareEdge`; `planned_prepare_trace_projects` maps each non-reflexive edge to a real `Step`.  The induction is not a list theorem detached from the lifecycle.  However, RTC always contains reflexivity, and this module supplies no closed state/assignments witnessing even one or two enabled edges.  The generic two-step theorem is conditional, so closed inhabitation remains unproved here. |
| `two_prepare_gate` is genuinely sequential | **PASS, conditional** | It defines `S1 = advancePrepare S assignment1` and `S2 = advancePrepare S1 assignment2`; the second checker, head computation, `Valid`, `LWF`, and version all come from `S1`, not from the original state.  The first step filters out its durable head and strictly shrinks `remaining`, so the second nonempty computed head cannot be the same claim set.  The result is nevertheless conditional on `hRemaining2` and a successful second assignment check; it is not a closed two-group fixture and does not explicitly state owner/group inequality. |
| Strict decrease and termination | **PASS, Prepare-only** | `afterPrepareGroup_remaining_card_lt` proves that every enabled head contains a claim made durable by the exact target and hence removed from the filtered remaining set.  `PreparePlanned.remaining_card_lt` lifts this to edges, and `plannedPrepareEdge_wellFounded` uses remaining-cardinality as a well-founded measure.  This excludes infinite `PreparePlanned` runs.  It does not prove progress, availability of fresh operation assignments, eventual preparation of every claim, or termination of a larger grammar containing topology/replanning/stuttering steps. |

## Dependency and circularity audit

The critical readiness chain is:

```text
source Valid + remaining.Nonempty
  -> computed firstGroup/headGroup
  -> BatchBound + CursorPhase + outside-zero
  -> derived HeadPhaseBound
  -> DurableEq + Envelope + Deadline + headGroup <= L
  -> actual promotedLoad <= capacity
  -> actual PrepareOK (with finite assignment-check soundness)
  -> Step.core (CoreStep.prepare ...) to exact prepareState
```

The target-invariant chain is independent of target certification:

```text
exact prepareState status/durable lemmas
  -> target tentative and remaining subsets of source-minus-head
  -> exact E and durable-load update
  -> Envelope, BatchBound, CursorPhase, and all structural fields
  -> target Valid
```

No edge theorem takes the desired readiness conclusion under another name.
`BatchBound`, `Envelope`, `Deadline`, `DurableEq`, and `CursorPhase` are strong
source invariants, but they describe the whole durable plan rather than a
caller-selected target or per-edge `PrepareOK`.  The proof therefore closes the
circularity problem at the scoped invariant level.

Two wording details should remain precise:

1. `owner_root_pure` is a source proposition in `Valid`, not yet the output of
   the separate executable owner-purity checker.  This file preserves the
   proposition across Prepare; it does not establish its initial authenticity
   or transport across topology changes.
2. The file comment calls the preserved batch accounting "exact," but the
   actual field is `B + E <= P`.  Exact durable exposure is proved; exact
   residual batch disposition is not.

## Trace and two-step nonvacuity attack

`PlannedPrepareTrace` is a real RTC, and any supplied non-reflexive edge carries
an actual successful `PreparePlanned`.  The safety theorem is therefore not
vacuous in its *step case*.  `two_prepare_gate` also prevents the common bug in
which a purported second step is accidentally taken again from `S`: its second
source is definitionally the first target, including updated tickets, status,
remaining set, `E`, and version.

What is missing is a closed theorem such as:

```text
exists S assignment1 assignment2 S1 S2,
  PreparePlanned S ... assignment1 S1 /\
  PreparePlanned S1 ... assignment2 S2
```

over a finite instance with two initially distinct nonempty groups and two
fresh operations.  In the current theorem, `hRemaining2` and
`hAssignment2` are premises.  Since assignment coverage/freshness can be
impossible when the operation namespace is too small or already bound, source
`Valid` and nonempty remaining do not themselves imply progress.  A small
closed `by native_decide`/kernel-checked fixture would upgrade the nonvacuity
row to PASS; it should assert the two computed heads or their disjointness as
well as the two `Step`s.

## Frozen-plan comparison

The accepted experiment plan requires the combined invariant

```text
d_t = d_0 + sum_i E_i
L_i + E_i <= R_i
B_i + E_i + W_i = P_i
```

plus a discrete lineage-leaf partition and a positive grammar covering plan
transport, deletion, Merge, Prepare, and ticket phases.  This module proves the
first two rows and only the monotone consequence `B_i + E_i <= P_i` needed for
Prepare scheduling.  Cleanup may remove additional batch claims; the resulting
slack is not recorded as computed withdrawal `W`, and prepared/withdrawn
identity is not retained in a leaf ledger here.  The separate `Plan.lean` has
an `AuthorityPlan` with `W` and exact accounting, but this review found no
theorem integrating that structure with `PlanInvariant.PlanData`'s multi-slot
readiness and RTC.  Results from the two modules must not be conjoined in prose
without an explicit bridge theorem.

Likewise, `PlannedPrepareEdge` contains only Prepare.  It cannot support a claim
that arbitrary Fork/Restore/Merge/restriction/ticket histories preserve this
`Valid`; those require later transport constructors and a combined trace
theorem.

## Build, source, and axiom audit

- The implementing agent froze the source after `invocation-019.log`; its
  targeted build succeeds.  `invocation-020-full-build.log` reports a successful
  full `lake build` with no pending jobs.
- I independently compiled the exact frozen source with pinned Lean 4.30.0 via
  `lake env lean -o /tmp/plan-invariant-semantic-review.olean
  AuthorityContinuity/PlanInvariant.lean`; it exited successfully.
- The reviewed source hash remained
  `b0f6f2dc48de118604765a5e4d03cda4423e3f7b17e0ef4bc4bd7a75e1161f02`
  after the replay.
- Static scans found no `sorry`, `admit`, project `axiom`, `hPfits`, or
  `hbatchP` in this module.  The only repository match for the broad token
  `unsafe` was ordinary English in an unrelated example comment.
- Explicit axiom checks for the paper-facing theorems, the derived phase
  theorem, strict-decrease lemmas, version/cardinality trace lemmas, and
  well-foundedness report only `propext`, `Classical.choice`, and
  `Quot.sound`; no `sorryAx` or project axiom appears.

## Defensible claim and prohibited inflations

The strongest defensible claim from this file is:

> A sequential durable controller can compute the next nonempty multi-slot
> owner group and, from a preserved source schedule invariant plus executable
> version and assignment checks, derive the repository's real atomic Prepare.
> Each successful Prepare preserves lifecycle authority safety and the same
> schedule invariant, advances the version, and strictly consumes the finite
> remaining batch; consequently every finite Prepare-only run is safe and the
> Prepare-only edge relation is well founded.

Do not inflate it, without additional integrated theorems and evidence, to:

- exact `B/E/W` residual accounting or preservation of zero-demand leaf
  identity;
- a full `PlanValid` theorem for Fork, Restore, Merge, restriction/Revoke,
  checkpoint, or ticket histories;
- a closed, demonstrated two-Prepare workload (the current gate is
  conditional);
- progress or successful completion whenever `remaining` is nonempty;
- concurrent linearizability, crash durability, stale-request rejection, or
  correctness of a SQLite/runtime CAS;
- physical at-most-once/exactly-once external effects;
- initial authenticity or topology preservation of `rootSlot` and
  `owner_root_pure`.

