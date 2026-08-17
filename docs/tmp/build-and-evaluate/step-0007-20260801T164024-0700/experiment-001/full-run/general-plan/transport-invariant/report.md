# Canonical plan-transport invariant closure

Date: 2026-08-01

## Verdict

PASS. The new independent module
`lean/AuthorityContinuity/PlanInvariantTransport.lean` constructs the only
admitted target plan from the source plan and the checked transfer map `rho`,
then reconstructs the complete target `PlanData.Valid` certificate. It does
not accept target validity, target readiness, a caller-selected target batch or
root map, or proposed target load bounds as premises.

Final source SHA-256:
`f8019a292b114a84e69efb0dd7a73fb42a00afd956514ee4c8b33dce37f83c9c`.

## Computed target and executable gate

`afterCanonical p tr` is definitionally:

- version `p.version + 1`;
- root map `PlanRootTransport.transportedRoot p.rootSlot tr`;
- remaining batch `Plan.childBatch tr p.remaining`; and
- unchanged `d0`, `cap0`, `slots`, `R`, `P`, and `E`.

The plan therefore follows the actual `rho` fibers. Canonical transfer does not
promote a claim, so durable accounting and the schedule rows remain unchanged.

`checkCanonicalPlan A p tr op offered` exposes exactly three executable
admission atoms:

1. the source plan version CAS `p.checkVersion offered`;
2. the repository's actual `checkCanonical A tr op`; and
3. exhaustive target tentative-owner/root purity on the computed root map.

The version result is reported separately from `Valid`, because the definition
of `Valid` contains no version field.

## Kernel-checked preservation

The proof reconstructs every target validity field:

- `afterCanonical_L_le` covers all target tentative demand at each root,
  including non-batch claims.
- `afterCanonical_B_le` covers the computed selected batch using checked fiber
  conservation.
- `afterCanonical_preserves_remaining_rooted` derives each target leaf, owner,
  and root from a real `rho` edge.
- `afterCanonical_preserves_owner_root_pure` derives owner/root purity from the
  executable target check, including rejection of `some`/`none` mixing.
- Root membership, durable equality, envelope, batch bound, deadline, and
  zero-outside-schedule facts are reconstructed from source validity and the
  computed target.
- `afterCanonical_preserves_cursorPhase` does not assume active-pair inclusion:
  target owners may change. Instead, every target active group is mapped to a
  real source active group at the same slot, which proves that the recomputed
  target cursor cannot move earlier and preserves zero future exposure.
- `afterCanonical_preserves_valid` assembles the complete target `Valid` from
  source `Valid`, successful `checkCanonical`, and the owner/root checker.
- `afterCanonical_preserves_headPhaseBound` derives readiness from the rebuilt
  target validity rather than storing or accepting a readiness certificate.

The projection-free theorem `afterTransferCore_preserves_valid` generalizes the
same proof. It requires only an actual authority equality
`A'.auth = tr.targetCore A allowed`, source `Valid`, `Transfer.CoreValid`, and
the executable owner/root check. This is the reusable plan theorem for a future
simulation-certified Merge once that transition exposes the required authority
equality; it does not assume or prove Merge admission itself.

## Actual lifecycle projection

`afterCanonical_actual_step` reaches the repository's authoritative
`Step.canonical`; no plan-specific shadow transition relation is introduced.
`checkedCanonical_preserves_all` combines source `LWF`, `AC`, `ActiveExact`, and
plan validity with the executable checks to derive:

- target `LWF`;
- target authority continuity `AC`;
- target `ActiveExact`;
- complete target plan `Valid`;
- the actual `Step A .tau target`; and
- target version `offered + 1`.

## Validation evidence

- `invocation-01.log` through `invocation-05.log`: retained incremental direct
  elaborations for load, structure, cursor, full validity/lifecycle, and the
  combined checker; all exit 0.
- `invocation-06-lake-build.log`: pre-generalization package build, exit 0,
  8,486 jobs.
- `invocation-07-generic-core.log`: retained generic-bridge elaboration failure;
  the target authority equality was initially hidden below `Plan.batchLoad`.
- `invocation-08-generic-core.log`: repaired direct elaboration after unfolding
  the batch-load wrapper, exit 0.
- `invocation-09-final-lake-build.log`: retained launch error from invoking Lake
  at the repository root rather than the `lean/` package directory; no build ran.
- `invocation-10-final-lake-build.log`: final package build from the correct
  directory, exit 0, 8,486 jobs.
- `static-scan.log`: no `sorry`, `admit`, custom axiom declaration, or
  `native_decide`.
- `axiom-audit.log`: all six printed headline theorems depend only on the
  accepted allowlist `[propext, Classical.choice, Quot.sound]`.

## Honest claim boundary

This closes the canonical Fork/Restore-shaped transfers represented by the
repository's `CanonicalOp`, and the plan-level core applies to any checked
`targetCore` with an exposed authority equality. It does not yet prove direct
Merge admission, arbitrary rollback, or preservation across every lifecycle
rule.

`transportedRoot` assigns `none` when a claim has no `rho` source. The current
`PlanData.Valid` consumes roots for tentative/remaining scheduling, so this is
enough for the theorem proved here. It does not preserve historical root
provenance for already prepared, withdrawn, or durable claim IDs; a separate
durable lineage ledger would be needed for that stronger property.

The owner/root check is a finite executable sufficient condition, not a proved
globally minimal or necessary condition. Its straightforward implementation may
be quadratic in the number of target claims. Finally, the theorem proves
logical lifecycle safety and schedule accounting, not physical exactly-once
external effects or compensation after dispatch.
