# Invocation 002 — unified grammar build and axioms

Attempt record:

| Attempt | Result | Note |
|---|---|---|
| 1 | proof-engineering failure | two `cases` alternatives supplied an extra explicit name for the `ticket` constructor |
| 2 | pass | corrected both alternatives to the constructor's one explicit proof field |

Final command:

```sh
PATH=/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin:$PATH \
  lake build AuthorityContinuity.PlanInvariantGrammar
```

Final result: exit 0; `Build completed successfully (8490 jobs).`

The retained `#print axioms` endpoints all reported exactly:

```text
[propext, Classical.choice, Quot.sound]
```

Endpoints audited:

- `CanonicalTransportPlanned.preserves_all`;
- `PositiveStep.preserves_safe`;
- `PositiveStep.version_mono`;
- `positive_trace_preserves`;
- `positive_trace_projects`; and
- `positive_trace_version_mono`.

No `sorryAx` or custom axiom appeared.
