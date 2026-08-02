# Experiment Plan: RQ4 History-Admission Scaling Boundary

## Research Question
- RQ exactly as written in the paper evidence contract: **RQ4: Is there a deployable algorithmic boundary? Can an industrial runtime obtain useful fast paths while failing closed on the general guarded case?**
- Specific uncertainty tested here: whether the source-native history-admission compiler and independent verifier complete deterministic small-manifest analysis through the documented 12-cell bound, how their runtime tracks expanded configurations and minimal nonfaces, and where overlapping controller products engage the 200,000-state fail-closed cap.
- Why the answer matters: the paper currently states finite caps but has no measured scaling curve; a reviewer cannot tell whether those caps are conservative engineering bounds, unreachable constants, or hiding immediate blow-up on intended small contracts.

## Paper-Value Admission
- Planned role: supporting.
- Largest credible paper story this experiment could unlock: the certifying artifact is practically usable for its explicitly claimed small-contract scope, while the observed curve and first rejected case make the exponential boundary and fail-closed behavior concrete rather than presenting caps as performance evidence.
- Strongest reviewer reject argument or load-bearing uncertainty addressed: “the exhaustive compiler/verifier may already be unusable near its advertised finite scope, and the controller-product cap is untested.”
- Independent evidence added beyond existing runs and published results: existing tests establish correctness on 2,166 three-cell refinement instances and individual cap checks; they do not measure end-to-end latency, sweep semantic-cell/minimal-nonface scale, or approach the controller pair-expansion iteration limit.
- Why the result is not tautological, already settled, or dominated: exponential state counts follow from the implementation, but the end-to-end compiler and independently reimplemented verifier costs, output growth, and exact cap-engagement point are empirical properties of the real artifact.
- Paper decision if positive: replace the scaling TODO with a bounded microbenchmark, retain the “small runtime contracts, not a scalability claim” scope, and report the cap boundary explicitly.
- Paper decision if contradictory, mixed, or inconclusive: reduce the practical scope or omit latency claims; if compiler/verifier disagree, outputs are nondeterministic, or caps fail open, treat the artifact result as invalid until repaired.
- Best alternative experiment and why this one has higher decision value: another litmus or exhaustive three-cell run would duplicate existing correctness evidence; a real runtime benchmark cannot test compiler scaling because no complete production manifest adapter exists.

## Expected And Alternative Outcomes
- Current expected answer: fresh-process CLI latency grows with expanded families and independently enumerated controller pair expansions; 12-cell threshold families complete, four overlapping six-cell controllers remain below the iteration limit, and the fifth controller is rejected at attempted iteration 200,001.
- Strongest competing explanation: parser/output serialization or minimal-nonface materialization, rather than controller-product enumeration, dominates enough to make state-count attribution misleading.
- Result that would contradict the expectation: failure or impractical runtime below the documented bounds, non-monotone order-of-magnitude behavior unexplained by recorded counts, compiler/verifier disagreement, nondeterministic output, or acceptance beyond a declared cap.

## Published Precedent And Real Assets
- Closest published protocol: a standard systems scale sweep with trend and saturation attribution; no external paper defines a benchmark for this new manifest format.
- Official system/model/data/benchmark/tool and version: the repository’s dependency-free `history_admission.compiler` and independently implemented `history_admission.verifier`, with constants imported from `history_admission.schema`.
- What is reused: the production CLI modules, parser, compiler, verifier, canonical JSON output, and documented finite caps.
- Necessary deviations or custom glue: one deterministic manifest generator and runner; it does not add a parser, semantic path, cap, or experiment-control interface to the compiler.

## Comparison
- Proposed system or method: the history-admission compiler and verifier on the same generated request.
- Main baselines and the competing position each represents: none; this is a bounded scaling characterization, not a superiority comparison.
- Why each main baseline needs a matched run instead of citation alone: not applicable.
- Controls or ablations, labeled separately: (1) small cell-family preflight; (2) one-controller product; (3) 13 cells, which must fail at the declared cell cap; (4) five overlapping controllers, whose analytically derived product loop exceeds 200,000 and must fail closed in both implementations.
- Conclusion if each main baseline matches or wins: not applicable; compiler/verifier disagreement invalidates the run rather than establishing a winner.
- Information, tuning, and compute fairness: both implementations receive identical JSON requests, run as fresh Python processes with `PYTHONHASHSEED=0`, and use the same repetition count; request generation and file creation are outside timed intervals.
- Split or leakage rule when relevant: not applicable.

## Workloads And Metrics
- Real workloads or tasks: deterministic synthetic manifests accepted through the artifact’s official CLI path. Cell sweep: `n={4,6,8,10,12}` with the downward-closed family `|C|<=n/2`, one controller, and all minimal nonfaces of size `n/2+1`. Controller sweep: six cells, full local/admitted powersets, and `c={1,2,3,4}` overlapping controllers; `c=5` is the predeclared cap failure.
- Primary metrics: median fresh-process end-to-end compiler and verifier wall time over five repetitions; an analytically reconstructed controller-product loop-iteration count for the deterministic workload. The production tools do not export this internal counter, so the paper must not label it as measured telemetry.
- Correctness check or ground truth: every passing compiler output is byte-identical across repetitions and accepted by the independent verifier; observed minimal-nonface count equals the combinatorial oracle; expected-failure rows exit nonzero with the exact declared-cap diagnostic.
- Repetitions, seeds, and uncertainty: five fresh processes per passing cell, reporting all raw times, median, min, max, and quartiles; workloads are deterministic and use no random seed.
- Cost estimate when material: under several minutes on one CPU; no network, model, or paid service.

## Planned Runs
| Run group | Role | Workload | System/method | Repetitions | Decision consequence |
|---|---|---|---|---:|---|
| cells | proposed | threshold families, 4--12 cells | compiler then verifier CLI | 5 | Measures finite-family/minimal-nonface curve through the documented bound |
| controllers | proposed | six cells, 1--4 overlapping co-live controllers | compiler then verifier CLI | 5 | Measures the pair-expansion curve below the iteration limit |
| cell-cap | control | 13 cells | compiler and verifier CLI | 1 each | Must reject at the cell bound |
| product-cap | control | six cells, 5 overlapping controllers | compiler and verifier CLI | 1 each | Must reject after attempting state 200,001 |

## Execution
- Authoritative command or workflow: `cd artifact && python3 bench_history_admission_scaling.py --output results/history_admission_scaling.json`.
- Real preflight case: one four-cell threshold manifest and one six-cell/one-controller manifest through compiler and verifier CLIs.
- Full completion rule: every planned passing repetition terminates with compiler exit 0 and verifier exit 0; output hashes are stable; both expected failures return the declared diagnostic; the raw JSON contains every timing and environment field.
- Raw-result path: `artifact/results/history_admission_scaling.json`.
- Checkpoint or recovery approach: output is written only after the complete matrix passes; rerun the single command after interruption.

## Interpretation
- Positive result: all correctness checks hold, median time is reported without extrapolation, and the state cap rejects the first predeclared over-cap controller row.
- Negative or contradictory result: report the observed boundary and reduce artifact scope; do not relabel an unexpected failure as success.
- Mixed or inconclusive result: preserve raw timings, avoid a paper latency number, and state which source of noise or missing attribution prevents interpretation.
- Initially proposed paper table: cells/configurations/minimal nonfaces with compiler/verifier median time, plus controller pair-expansion counts ending in the fail-closed limit row.

## Post-review scope correction

The repository evaluation contract forbids paper-facing latency before complete runtime enforcement. Therefore timings remain in the internal artifact report. The paper-facing evidence, if used, is limited to bounded family/certificate counts and fail-closed engagement of the source-cell and controller pair-expansion limits; it must not be presented as deployability or throughput.

## Reproducibility Notes
- Software and data versions: record Python, platform, processor, repository commit if available, and schema cap constants in the raw output.
- Config and seed notes: no randomness; `PYTHONHASHSEED=0`; five new processes per passing point.
- Known deviations: wall time includes Python startup and JSON input/output because it measures the documented CLI path; ambient host load and filesystem cache are not controlled, so results characterize this machine rather than establish cross-machine performance.
