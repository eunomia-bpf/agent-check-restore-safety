# Head-phase structural derivation

Status: **PASS**

## Result

`AuthorityContinuity.PlanInvariant.PlanData.head_phase_bound_of_structural`
derives `p.HeadPhaseBound A` from exactly:

1. `E_outside_zero`,
2. `p.BatchBound A`, and
3. `p.CursorPhase A`.

It does not accept `HeadPhaseBound`, readiness, a capacity inequality, or any
equivalent conclusion as a premise.  The proof is stronger than the initially
proposed dependency set: neither `root_mem` nor `P_outside_zero` is needed.
The equation's current-slot exposure occurs verbatim on the right-hand side;
planned demand outside `p.slots` can only increase the right-hand side.

## Argument

For every slot `t` in the finite total-exposure sum, totality of the linear
order gives three cases around the current first-group slot `s`:

- `t < s`: if `t` is scheduled, `BatchBound` gives
  `B(t,k) + E(t,k) <= P(t,k)`, hence `E(t,k) <= P(t,k)`; if it is outside the
  schedule, `E_outside_zero` gives `E(t,k) = 0`.
- `t = s`: keep `E(s,k)` exactly.
- `s < t`: `CursorPhase` gives zero exposure for a scheduled later slot, and
  `E_outside_zero` gives zero exposure for an outside slot.

Summing these pointwise inequalities yields

`totalE E k <= priorP P s k + E s k`.

The equality `firstGroup A p = some (s,b)` is used only to instantiate
`CursorPhase`; no stored cursor and no independent head-phase oracle is used.

## Verification

- Source: `lean/AuthorityContinuity/PlanPhaseDerivation.lean`
- SHA-256: `b32a788a4af1e624cc1fa0d5cb2d7e6999f19fdcfd51b5b53d305a1cf9f34708`
- Single-file compile log: `invocation-03.log`
- Project-target build log: `invocation-04-lake-build.log`
- Commands: pinned Lean 4.30.0 `lake env lean
  AuthorityContinuity/PlanPhaseDerivation.lean` and `lake build
  AuthorityContinuity.PlanPhaseDerivation`
- Exit status: 0
- `#print axioms`: `[propext, Classical.choice, Quot.sound]`
- No `sorry`, `admit`, custom `axiom`, or `native_decide` occurs in the module.

Invocations 1 and 2 are retained.  Invocation 1 found only an incomplete
Finset normalization proof; invocation 2 compiled but had an unnecessary
`change` warning.  Invocations 3 and 4 are the clean final single-file and
project-target builds (apart from informational linter warnings).

## Integration consequence

`head_phase_bound : p.HeadPhaseBound A` is logically redundant as a field of
`PlanData.Valid`.  After that field is removed, any former use

`hv.head_phase_bound`

can be replaced with

`head_phase_bound_of_structural hv.E_outside_zero hv.batch_bound hv.cursor_phase`.

This report does not claim that `CursorPhase` itself is derivable from the
other fields; it remains the semantic schedule-progress invariant that must be
established initially and preserved by lifecycle/plan transitions.
