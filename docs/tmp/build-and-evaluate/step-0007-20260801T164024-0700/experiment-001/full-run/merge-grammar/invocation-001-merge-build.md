# Invocation 001 — Merge bridge build and axioms

Command:

```sh
PATH=/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin:$PATH \
  lake build AuthorityContinuity.PlanInvariantMerge
```

Result: exit 0; `Build completed successfully (8487 jobs).`

The retained `#print axioms` endpoints all reported exactly:

```text
[propext, Classical.choice, Quot.sound]
```

Endpoints audited:

- `afterSimulationMerge_preserves_valid`;
- `SimulationMergePlanned.preserves_all`;
- `afterDirectMerge_preserves_valid`;
- `DirectMergePlanned.preserves_all`.

The concrete witness was deliberately separated from the generic module and
built with:

```sh
PATH=/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin:$PATH \
  lake build AuthorityContinuity.PlanInvariantMergeExamples
```

Result: exit 0; `Build completed successfully (8489 jobs).`  Its two negative
witness endpoints reported the same axiom allowlist.

No `sorryAx` or custom axiom appeared.  Only ordinary
unused-section-variable lint warnings were emitted.
