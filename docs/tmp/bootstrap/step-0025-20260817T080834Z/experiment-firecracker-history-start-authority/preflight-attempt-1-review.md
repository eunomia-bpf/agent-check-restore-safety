# Preflight attempt 1 disposition

- Result: **failed before any `InstanceStart`**.
- Retained evidence:
  `preflight-attempt-1/`.
- Exact cause: the protected cell encoded typed runtime facts in Go struct
  field order, while `LifecycleGuard` requires the generic key-sorted JSON
  representation. The guard rejected those bytes as non-canonical.
- Safety disposition: fail closed. DeathStarBench received zero deliveries,
  the source cell emitted no `ready` event, the configured Firecracker process
  was reaped, and the residual-process check found no live session.
- Scientific disposition: infrastructure-only failure; this attempt supplies
  no H1/H0/control result and is not admissible evidence.
- Required correction before attempt 2: canonicalize the typed runtime facts
  through a number-preserving generic JSON representation and add a regression
  test that includes an integer above `2^63`.
