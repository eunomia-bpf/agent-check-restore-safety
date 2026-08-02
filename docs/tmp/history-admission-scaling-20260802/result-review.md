# Independent Scaling Result Review

## Verdict

- Run status: **VALID and complete for the approved matrix; provenance-incomplete as a historical archive.**
- Hypothesis status: **SUPPORTED for bounded completion, determinism, and engagement of the two exercised limits; MIXED for causal runtime attribution.**
- Research role: supporting small-manifest mechanism evidence, not an RQ4 deployability or throughput result.

## Independent checks

The reviewer and a fresh recomputation subreview checked the plan, runner, raw JSON, production compiler/verifier loops, and paper evidence contract without editing the experiment. They found:

- all five cell rows and four passing controller rows contain five compiler and five verifier processes: 90 passing invocations;
- the two failure controls add four expected-failure invocations, for 94 represented subprocesses total;
- an independent 103-check recomputation found no arithmetic or summary-statistic errors;
- a fresh temporary rerun reproduced every non-timing field, including request/result sizes, hashes, statuses, and diagnostics;
- all stored family sizes, minimal-nonface counts, analytical loop counts, medians, inclusive quartiles, and extrema are correct; and
- the analytical controller formula exactly matches the counter increment sites in both production implementations.

## Required interpretation

The production `product_states` variable does not count distinct states. It increments once for each `(accumulated partial configuration, local choice)` pair before union deduplication. The accurate experiment label is **analytically reconstructed pair-expansion iterations**. Only 64 distinct physical configurations remain in every controller-sweep row.

For five controllers, 202,688 is the hypothetical uncapped full count. The compiler and verifier actually stop at attempted iteration 200,001. The diagnostic retains the production wording `controller product exceeds 200000 states`, but the paper/report must not adopt that wording as its metric.

The source-cell and controller-product iteration limits were exercised. The target-cell, raw controller-count, and expanded-configuration limits were not. Therefore the original aggregate `declared_caps_failed_closed` label was overbroad and had to be split into two exercised-limit claims.

## Attribution limits

The controller sweep provides a useful mechanism isolation: final physical configurations remain 64 and JSON sizes change only modestly while pair-expansion iterations grow from 64 to 70,592. Even there, the millisecond curve is startup-dominated and is not an asymptotic fit.

The cell sweep is descriptive only. Semantic cells, number of maxima, family configurations, minimal nonfaces, request bytes, result bytes, parser work, and serialization all co-vary. At 12 cells the request/result are 1,188,580/1,940,181 bytes, so the timing cannot be causally attributed to one algorithmic phase or presented as worst-case 12-cell complexity.

## Provenance qualification

The timed run occurred in a dirty worktree while the runner and result were untracked. Per-case requests, results, and seals were created under a temporary directory and deleted; only timing arrays, sizes, deterministic hashes, statuses, and diagnostics survive. The final report records SHA-256 digests of the exact historical runner/compiler/verifier/schema byte images, which improves identification but does not make the historical wall-time samples independently auditable.

A later paper-facing rerun should use a clean pinned tree and preserve one canonical request/result/seal per passing row plus failure exit/stderr records. Preserving all five byte-identical outputs is unnecessary.

## Paper decision

The experiment shows that the bounded artifact completes the selected 12-cell contract and fails closed on the two exercised limits. It does not test an industrial runtime, fast path, complete mediation, a baseline, memory use, heterogeneous local families, or real-manifest prevalence.

Because `docs/evaluation.md` forbids paper-facing latency before enforcement is complete, the paper may use bounded family/certificate counts and fail-closed limit engagement, but the detailed timings remain internal artifact evidence until that contract changes.
