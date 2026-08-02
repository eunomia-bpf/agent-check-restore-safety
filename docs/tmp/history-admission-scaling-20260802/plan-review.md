# Scaling Plan Review

## Reviewer and status

- Reviewer: root research task, after inspecting the production controller-product loop.
- Fresh independent reviewer: unavailable because all collaboration slots were occupied; this limitation is recorded rather than treating the root review as independent.
- Verdict: **proceed**, with one precision requirement and one mandatory boundary preflight.

## Findings

- No blocking defect was found in the workload design.
- `controller_future_maxima` is expanded downward, so the declared maximum containing all controllers causes the compiler and verifier to analyze every controller subset.
- With six cells and a full local powerset of size `L=64`, the deterministic source-loop count is
  `(2^c - 1)L + (c 2^(c-1) - (2^c - 1))L^2`.
- This reconstructs 70,592 loop iterations for four controllers and 202,688 for five controllers. Therefore four controllers should pass and five should hit the 200,000-state cap on the 200,001st attempted state.
- The count is not exposed by the production result format. It must be described as analytically reconstructed from the fixed workload and inspected deterministic loop, not as measured internal telemetry.

## Mandatory preflight

Before the full five-repetition matrix, execute the real compiler and verifier CLI paths on:

1. the largest passing controller row (`c=4`), and
2. the first planned failing row (`c=5`).

Both tools must accept `c=4`; both must reject `c=5` with `controller product exceeds 200000 states`. A mismatch blocks the full run.
