# Invocation 001 — build and axiom audit

Date: 2026-08-01 (America/Vancouver)

Command:

```sh
PATH=/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin:$PATH \
  lake build AuthorityContinuity.PlanInvariantDrop
```

Result: exit 0; `Build completed successfully (8485 jobs).`

The module's retained `#print axioms` checks reported the same allowlist for
all paper-facing endpoints below:

```text
afterRestriction_preserves_valid: [propext, Classical.choice, Quot.sound]
afterRestriction_actual_step: [propext, Classical.choice, Quot.sound]
afterRestriction_preserves_all: [propext, Classical.choice, Quot.sound]
afterRevoke_preserves_valid: [propext, Classical.choice, Quot.sound]
afterRevoke_actual_step: [propext, Classical.choice, Quot.sound]
afterRevoke_preserves_all: [propext, Classical.choice, Quot.sound]
RestrictionPlanned.preserves_all: [propext, Classical.choice, Quot.sound]
RevokePlanned.preserves_all: [propext, Classical.choice, Quot.sound]
```

There was no `sorryAx`, custom axiom, build error, or warning specific to proof
soundness.  Lean emitted only existing/ordinary unused-section-variable
lint warnings.
