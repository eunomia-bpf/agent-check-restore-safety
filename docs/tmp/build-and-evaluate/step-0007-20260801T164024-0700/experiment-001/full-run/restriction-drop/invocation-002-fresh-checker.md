# Invocation 002 — fresh kernel replay

Command:

```sh
PATH=/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin:$PATH \
  lake env leanchecker --fresh AuthorityContinuity.PlanInvariantDrop
```

Result: exit 0 with no diagnostic output.

This replay checked the generated module in a fresh `leanchecker` process
rather than relying only on the incremental Lake build cache.

