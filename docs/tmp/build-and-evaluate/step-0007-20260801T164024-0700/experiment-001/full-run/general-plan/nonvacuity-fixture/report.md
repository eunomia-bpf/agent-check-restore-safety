# Closed two-slot scheduler non-vacuity fixture

Date: 2026-08-01

## Verdict

PASS. The new module
`lean/AuthorityContinuity/PlanInvariantExamples.lean` provides a completely
closed finite witness for the frozen multi-slot/two-Prepare scheduler. Its
headline theorem has no arguments: the source invariant, both remaining-work
facts, both executable assignment checks, and both version checks are proved
inside the fixture.

Final source SHA-256:
`e31a7be0ddd85274353196fb3cc040cbda73dca211145e10c521ef86d8042178`.

## Concrete model

The fixture uses:

- one resource coordinate (`Fin 1`);
- two claims, branches, grants, operations, and schedule slots (`Fin 2`);
- capacity 2 and unit demand for each claim;
- claim 0 tentatively owned by branch 0 and rooted at slot 0;
- claim 1 tentatively owned by branch 1 and rooted at slot 1;
- the complete finite configuration contract (`allowed = Finset.univ`);
- open branch and grant epochs, with no pre-existing tickets or receipts; and
- plan rows `R = P = 1`, `E = 0`, baseline durable load 0, and both claims in
  `remaining`.

Thus the source has two genuinely distinct nonempty owner groups at two slots.
The executable first group is `(0, 0)`. Unit reservation at slot 0 fits directly;
slot 1 has one unit of prior planned work plus one unit of reservation, exactly
matching capacity 2.

The module independently proves the concrete source satisfies:

- lifecycle `LWF`;
- authority continuity `AC`;
- `ActiveExact`; and
- the complete `PlanData.Valid`, including envelope, deadline, batch bound, and
  cursor phase.

## Executable two-step run

`assignment₀` binds operation 0 to claim 0. The concrete Boolean
`Plan.checkAssignment` proves membership, coverage, injectivity, and freshness.
After the first exact `prepareState`, the remaining batch is nonempty and the
computed next first group is `(1, 1)`.

`assignment₁` binds the still-fresh operation 1 to claim 1. Its complete
assignment check is again evaluated to `true` on the actual first target state.
After this step, the computed remaining batch is exactly empty.

`concrete_two_prepare_gate` directly instantiates the frozen
`PlanData.two_prepare_gate`, showing that its premises are jointly satisfiable.

The stronger unconditional theorem `concrete_two_prepare_execution` exhibits
the exact computed states `state₁` and `state₂` and proves:

- `PreparePlanned sourceState 0 assignment₀ state₁`;
- `PreparePlanned state₁ 1 assignment₁ state₂`;
- both transitions project to the repository's actual `Step ... .tau ...`;
- the final plan is `Valid` in the actual final lifecycle;
- the version advances from 0 to 2;
- remaining cardinality strictly decreases on each edge; and
- the final remaining set is empty.

No target `Valid`, readiness, second-step nonemptiness, assignment validity, or
freshness proposition is an argument to this theorem. First-target validity and
lifecycle safety are obtained from the first `PreparePlanned` preservation
theorems; the finite second-step facts are computed in the fixture.

## Validation evidence

- `invocation-01.log`: retained initial elaboration failures (incorrect
  namespace projection and attempted direct `Decidable` synthesis for
  structure-valued invariants).
- `invocation-02.log`: first successful direct elaboration after constructing
  `LWF` and `Valid` field by field and computing their finite arithmetic
  subgoals.
- `invocation-03.log`: retained argument-position error from the first direct
  `two_prepare_gate` instantiation.
- `invocation-04.log`: corrected direct elaboration, exit 0.
- `invocation-05-final-lake-build.log`: final package build, exit 0, 8,485 jobs.
- `static-scan.log`: no `sorry`, `admit`, custom axiom declaration, or
  `native_decide`.
- `axiom-audit.log`: all six audited source/headline theorems depend only on
  `[propext, Classical.choice, Quot.sound]`.

## Claim boundary

This is a non-vacuity and executable vertical witness, not a scale benchmark.
It demonstrates two slots, two changing owner groups, fresh durable ticket
installation, exact cleanup, invariant preservation, actual lifecycle steps,
and termination of this finite tail. General arbitrary-length safety and
well-foundedness remain supplied by the frozen abstract theorems in
`PlanInvariant`; this fixture does not replace them.
