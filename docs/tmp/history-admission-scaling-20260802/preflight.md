# Scaling Experiment Preflight

## Status

**PASS.** The real production compiler and independent verifier CLI paths completed the smallest cell/controller smoke cases and the largest planned passing controller case. Both implementations rejected the first planned over-cap case with the exact predeclared diagnostic.

## Command

From `artifact/`, a temporary-directory Python driver imported only the deterministic request builders from `bench_history_admission_scaling.py`, then invoked:

- `python3 -m history_admission.compiler REQUEST --output RESULT`
- `python3 -m history_admission.verifier REQUEST RESULT --output SEAL`

Request generation and file writes were outside the timed CLI interval. Temporary inputs and outputs were deleted at process exit.

## Observations

| Case | Analytical loop iterations | Compiler | Verifier | Approx. wall time (compiler / verifier) |
|---|---:|---|---|---:|
| 4 threshold-family cells | 11 | exit 0, exact coordination | exit 0, valid seal | 51.832 / 50.870 ms |
| 1 full-powerset controller | 64 | exit 0, exact coordination | exit 0, valid seal | 51.187 / 53.463 ms |
| 4 overlapping controllers | 70,592 | exit 0, exact coordination | exit 0, valid seal | 92.911 / 88.994 ms |
| 5 overlapping controllers | 202,688 | exit 2 | exit 2 | 167.671 / 155.381 ms |

The five-controller diagnostic in both stderr streams contained exactly:

```text
controller product exceeds 200000 states
```

## Decision

Proceed to the approved full matrix. These one-shot wall times are preflight diagnostics only and are not paper results.
