# Invocation 003 — fresh kernel replay

Commands:

```sh
PATH=/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin:$PATH \
  lake env leanchecker --fresh AuthorityContinuity.PlanInvariantGrammar

PATH=/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin:$PATH \
  lake env leanchecker --fresh AuthorityContinuity.PlanInvariantMergeExamples
```

Both final post-refactor commands exited 0 with no diagnostic output.  Their
dependency closures both include the generic Merge module.
