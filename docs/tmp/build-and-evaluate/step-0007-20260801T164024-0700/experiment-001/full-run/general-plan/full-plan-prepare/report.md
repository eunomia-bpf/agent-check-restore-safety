# Full rich-schedule and exact-leaf invariant: Prepare closure

Date: 2026-08-01

## Verdict

PASS for the prioritized owner-group Prepare bridge. The new independent
module `lean/AuthorityContinuity/FullPlanInvariant.lean` closes the semantic
gap between the rich multi-slot `PlanInvariant.PlanData.Valid` certificate and
the finite `Plan.AuthorityPlan` leaf/disposition ledger with exact
`B + E + W = P` accounting.

Final source SHA-256:
`bb853c33f455022d25e94cb42e41b9dd5e56bc57b3da65feba5f0e0969942cc4`.

No existing/frozen module was edited.

## Combined representation

`FullPlan` pairs:

- `schedule : PlanInvariant.PlanData`, which carries the multi-slot safety
  schedule; and
- `ledger : Plan.AuthorityPlan`, which gives every finite claim ID an optional
  `remaining`, `prepared`, or `withdrawn` disposition and stores exact `W`.

`Coherent A p` makes the representation agreement explicit:

- equal durable versions;
- exactly equal remaining sets;
- globally equal root functions (stronger than extant-leaf-only equality);
- equal `R`, `P`, and `E` rows; and
- ledger `currentSlot` equal to the schedule's executable first-group slot
  whenever work remains.

`FullInvariant A p` contains source `PlanData.Valid`, this coherence proof, and
the ledger's exact accounting. Source exact accounting is necessarily part of
the inductive invariant; no target exact-accounting proposition is accepted.

## Computed Prepare target

`FullPlan.afterPrepare` computes both target components from the source and the
actual assignment. Its lifecycle projection is the repository's exact
`prepareState A (schedule.headGroup A) assignment`.

The disposition computation has three semantic cases:

1. a computed head-group leaf becomes `prepared`;
2. a leaf present in the actual post-cleanup schedule remains `remaining`;
3. any other source remaining leaf removed by cleanup becomes `withdrawn`.

Other established dispositions are preserved. A defensive fourth branch
retires an impossible ghost `remaining` disposition; source coherence proves
that such a ghost cannot occur.

The theorem `source_remaining_classified` proves this case split, and
`afterPrepareLedger_remaining` proves that the finite ledger's target remaining
set is exactly the schedule's actual filtered target—not a caller-supplied
batch. `zeroDemand_source_leaf_visible` proves every source remaining leaf has
an explicit post-state disposition even when its whole demand vector is zero.
Thus vector arithmetic cannot erase discrete leaves.

## Exact withdrawal computation

For every slot and coordinate, the target ledger defines:

```text
W' = W + (B_old - (promotedAt + B_target))
```

Here `promotedAt` is computed from the executable first owner group and is zero
outside its slot. `B_target` is evaluated from the actual post-cleanup rich
schedule and actual `prepareState`. No target `W`, target batch, or withdrawal
delta is an argument.

The proof establishes:

```text
promotedAt + B_target <= B_old
E' = E + promotedAt
P' = P
```

At the head slot, the first inequality is the frozen
`afterPrepareGroup_B_add_batchLoad_le` theorem, which accounts simultaneously
for promotion and cleanup. At all other slots it follows from
`afterPrepareGroup_B_le`. With source coherence and source
`B + E + W = P`, natural-number arithmetic derives target exact accounting.
This is kernel checked by `FullPlan.afterPrepare_exact`.

## End-to-end gate

`FullState.schedulerState` projects the wrapper to the frozen rich scheduler.
`FullState.preparePlanned` constructs the existing
`PlanInvariant.PlanData.PreparePlanned`; it does not introduce a shadow
transition relation.

The headline `FullState.checkedPrepare_preserves_full` takes only:

- source lifecycle `LWF`;
- source `FullInvariant`;
- source remaining nonemptiness;
- successful executable schedule-version CAS; and
- successful executable assignment check.

It derives:

- the existing authoritative `PreparePlanned` edge;
- the repository's actual `Step ... .tau ...`;
- complete target `FullInvariant` (rich `Valid`, coherence, and exact ledger
  accounting);
- both target versions equal `offered + 1`; and
- strict decrease of remaining cardinality.

There is no target plan, ledger, disposition map, `W`, `Valid`, coherence, or
`ExactAccounting` premise.

## Validation evidence

- `invocation-01.log`: retained initial syntax and proof-shaping failures.
- `invocation-02.log`: computed ledger, classification, coherence, and load
  bridge directly elaborate.
- `invocation-03.log`: retained namespace-projection failure in the first exact
  accounting assembly.
- `invocation-04.log`: retained arithmetic countermodel, which exposed a
  missing definitional normalization between wrapper target and rich target.
- `invocation-05.log`: exact accounting directly elaborates after adding the
  explicit target-B bridge.
- `invocation-06.log`: end-to-end `PreparePlanned`/actual-Step/FullInvariant
  theorem directly elaborates.
- `invocation-07.log`: final classification and visible `W` equation directly
  elaborate.
- `invocation-08-final-lake-build.log`: final package build, exit 0, 8,485
  jobs.
- `static-scan.log`: no `sorry`, `admit`, custom axiom declaration, or
  `native_decide`.
- `axiom-audit.log`: all six audited headline theorems depend only on
  `[propext, Classical.choice, Quot.sound]`.

## Deliberate boundary and transfer coherence issue

This module closes actual owner-group Prepare, including deterministic owner
cleanup. Canonical/targetCore and restriction/drop extensions were deliberately
not added before this bridge was complete.

There is a real policy choice before mechanically composing the existing
canonical proofs: rich `afterCanonical` transports the global root map through
`rho` and assigns `none` to IDs without a source edge, whereas the older
`AuthorityPlan.afterTransfer` preserves roots for non-child historical leaves.
The new wrapper deliberately requires global root equality, so those two
targets are not coherent for prepared/withdrawn history without first choosing
one authoritative historical-root policy. Weakening coherence to remaining
leaves would avoid the proof obligation but would reopen the reviewed lineage
gap. A principled canonical extension should therefore compute a single global
root target and re-prove exact transfer accounting against it rather than
silently combining the two incompatible targets.

Restriction/drop similarly needs a computed disposition and `W` delta for
every leaf removed by the actual restriction. These are follow-on transition
proofs, not assumptions hidden in the Prepare result.
