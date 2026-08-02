# History-Admission Scaling Experiment Report

## Outcome

The approved supporting experiment completed. On this machine, both production CLI implementations completed every planned passing row, emitted deterministic results across five fresh-process repetitions, and agreed on every result. The 12-cell threshold-family row completed with compiler/verifier medians of 1.094/2.328 seconds. The controller sweep exposed exponential intermediate pair expansion even though union deduplication kept the final physical family at 64 configurations: the analytically reconstructed loop count rose from 64 at one controller to 70,592 at four controllers. The fifth controller's hypothetical uncapped count is 202,688, and both implementations failed closed when their actual loop counter attempted iteration 200,001.

This supports only the claimed small-contract algorithmic boundary. It is not a production-throughput, real-workload-prevalence, or cross-machine scalability result.

## Workloads

### Semantic-cell and minimal-nonface sweep

For each even `n` in `{4,6,8,10,12}`, the admitted, candidate, source, and one-controller local family was the threshold downset

```text
D_n = { C subseteq [n] : |C| <= n/2 }.
```

It has `sum_{i=0}^{n/2} binom(n,i)` configurations and `binom(n,n/2+1)` minimal nonfaces. This keeps the semantic construction fixed while scaling both finite-family enumeration and the coordination certificate.

### Overlapping-controller product sweep

The controller sweep fixed six semantic cells and a full 64-configuration local and admitted powerset. It varied `c` from one through four overlapping controllers and declared all controllers co-live. Downward closure therefore includes all `2^c` controller subsets.

The production result does not export its internal counter, named `product_states` in the source. It counts pair-expansion iterations, not distinct states. The number below is reconstructed from the deterministic workload and the inspected source loop. For a local family of size `L=64`, each nonempty controller subset performs `L` pair expansions for its first controller and `L^2` for every later controller, because union deduplication leaves `L` distinct partial configurations. Summing over all subsets gives

```text
(2^c - 1)L + (c 2^(c-1) - (2^c - 1))L^2.
```

The controller-product control establishes the boundary independently of this label: four controllers complete, while both implementations stop the five-controller workload with the production diagnostic `controller product exceeds 200000 states`. The report retains that string only as an exact diagnostic.

## Results

All times are fresh-process end-to-end CLI wall time, including Python startup and JSON I/O. Request generation and file creation are excluded. Each passing row reports the median and observed `[min,max]` over five repetitions.

### Cell sweep

| Cells | Expanded configurations | Minimal nonfaces | Request / result bytes | Compiler ms | Verifier ms |
|---:|---:|---:|---:|---:|---:|
| 4 | 11 | 4 | 6,111 / 10,352 | 50.151 `[49.319,50.488]` | 50.880 `[49.333,51.112]` |
| 6 | 42 | 15 | 18,045 / 29,320 | 52.187 `[51.431,54.487]` | 53.856 `[52.816,54.773]` |
| 8 | 163 | 56 | 67,319 / 109,220 | 65.166 `[55.161,74.981]` | 74.273 `[61.673,82.166]` |
| 10 | 638 | 210 | 278,986 / 454,361 | 139.474 `[137.810,140.944]` | 224.668 `[223.845,228.511]` |
| 12 | 2,510 | 792 | 1,188,580 / 1,940,181 | 1,094.182 `[1,075.578,1,104.042]` | 2,328.204 `[2,301.280,2,362.037]` |

The sharp rise at 12 cells coincides with both a 2,510-configuration family and a 792-minimal-nonface certificate whose serialized result is 1.94 MB. The experiment does not isolate enumeration, obstruction construction, serialization, and parsing costs, so it does not attribute that rise to one component.

### Controller sweep

| Controllers | Co-live subsets | Analytical source-loop iterations | Final physical configurations | Request / result bytes | Compiler ms | Verifier ms |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 64 | 64 | 5,589 / 8,920 | 51.302 `[50.859,51.981]` | 53.160 `[52.607,54.031]` |
| 2 | 4 | 4,288 | 64 | 7,034 / 9,399 | 54.627 `[53.412,57.645]` | 54.653 `[52.838,56.209]` |
| 3 | 8 | 20,928 | 64 | 8,479 / 9,878 | 63.378 `[62.960,63.902]` | 63.182 `[62.628,63.374]` |
| 4 | 16 | 70,592 | 64 | 9,924 / 10,357 | 92.005 `[91.303,92.523]` | 89.592 `[89.279,90.437]` |

The fixed final family and slowly growing JSON sizes make the controller sweep a useful isolation control: the hidden work increases because the algorithm enumerates overlapping local products before unions collapse to the same 64 configurations. At these small times, process startup is a large fixed cost; no asymptotic timing fit is claimed.

### Fail-closed controls

| Control | Planned analytical size | Compiler | Verifier |
|---|---:|---|---|
| 13 semantic cells | 4,096 threshold configurations | exit 2: `source must declare between 1 and 12 cells` | same exit and diagnostic |
| 5 overlapping controllers | 202,688 hypothetical uncapped iterations | exit 2 at attempted iteration 200,001: `controller product exceeds 200000 states` | same exit and diagnostic |

The 13-cell row tests the declared source-cell bound. The five-controller row remains below the separate ten-controller manifest bound and therefore specifically exercises the cumulative pair-expansion iteration limit. Target-cell, controller-count, and expanded-configuration limits were not tested.

## Correctness and reproducibility checks

- All compiler-result hashes and verifier-seal hashes were identical across the five repetitions for every passing row.
- Every compiler output reported exact coordination and was accepted by the independently implemented bit-mask verifier.
- Every observed minimal-nonface count matched its combinatorial oracle.
- Both exercised-limit controls returned the predeclared error code and exact diagnostic in both implementations.
- `python3 -m py_compile artifact/bench_history_admission_scaling.py` passed.
- From `artifact/`, `python3 -m unittest -v test_history_admission` ran the 31 focused history-admission tests in 2.196 seconds; all passed. This is a focused subset of the paper's 55-test total artifact suite, not a replacement count.
- From `artifact/`, `python3 -m unittest discover -v` ran all 55 artifact tests in 2.189 seconds; all passed.

One initial test invocation was accidentally issued from the repository root, where the top-level module name is not discoverable, and failed with `ModuleNotFoundError`. Repeating the same command from the documented `artifact/` working directory passed. This harness-location mistake did not affect the benchmark process or raw result.

## Commands

Authoritative full run:

```bash
cd /home/yunwei37/workspace/my-paper-work/agent-check-restore-safety/artifact
python3 bench_history_admission_scaling.py \
  --output results/history_admission_scaling.json
```

Regression suite:

```bash
cd /home/yunwei37/workspace/my-paper-work/agent-check-restore-safety/artifact
python3 -m unittest -v test_history_admission
python3 -m unittest discover -v
```

Raw result:

- path: `artifact/results/history_admission_scaling.json`
- bytes: 16,223
- SHA-256: `836092d2eb223ef58c22d08129e06a86b127b7da0b2fba6b56e2ab11370e5ed1`
- repository base commit recorded by the runner: `0ed19b32307ed78b245909406909ffb34436fcaf`
- run worktree: dirty; the benchmark script and concurrent paper changes were not yet committed
- exact historical source hashes: runner `3de1de713ba8f8cbd44d031f1a1d2aaae459f7b0d14a6140e5f19ec01bba81bd`, compiler `0d57f410099f4799e7bc9d32b5339bac21fdf3e48a3c278dd47c4d13026a76ff`, verifier `ead60debc3ee76fe9159c0eaffdb50596bc9fd7ec49c2a478b49914d8aecc16f`, schema `2c4a245eeac8e7f178a911176b3de28ab28c3e013b22cfdbe7086941727f9ec2`
- environment: CPython 3.12.3, Linux 6.15.11 x86-64, 24 logical CPUs, `PYTHONHASHSEED=0` in timed children

## Independent result review

Verdict: **valid and complete for the approved matrix, but provenance-incomplete as a historical archive**. The bounded-completion, determinism, and exercised-limit hypotheses are supported; causal runtime attribution is mixed.

The reviewer independently recomputed 103 arithmetic/statistical checks with zero errors and performed a fresh temporary rerun that reproduced every non-timing field. It confirmed 90 passing timed subprocesses plus four expected-failure subprocesses. It also required the narrowed pair-expansion terminology, the two-limit correctness split, and the dirty-worktree/archive qualification now reflected in the raw metadata and this report. The full review is in `docs/tmp/history-admission-scaling-20260802/result-review.md`.

## Interpretation for RQ4

The positive conclusion is deliberately narrow: the certifying compiler and independent verifier are executable through one nontrivial 12-cell/2,510-configuration/792-nonface contract on the measured host, and the exercised source-cell and controller-product iteration limits fail closed. The product sweep also validates why a second bound beyond final-family size is necessary: 70,592 intermediate pair expansions can collapse to only 64 physical configurations.

The result does not show that 12 cells or a 200,000-iteration limit are optimal industrial defaults, that real Claude/Codex manifests usually fit them, or that a dispatch-owning runtime can generate complete manifests. Under the current evaluation contract, the paper may use bounded family/certificate counts and fail-closed limit engagement, but not these latency measurements or a deployability/throughput claim. Detailed timings remain internal artifact evidence.

## Limitations

- The manifests are deterministic synthetic contracts chosen to isolate the algorithms; they do not estimate real-agent workload prevalence.
- Wall time is machine-specific and includes process startup and JSON I/O. Ambient host load and filesystem cache were not controlled.
- The pair-expansion values are source-grounded analytical reconstructions, not exported or measured production telemetry.
- The cell sweep changes several correlated costs at once: family size, minimal-nonface count, request/result size, parsing, and certificate construction.
- The benchmark exercises compiler/verifier analysis, not an adapter, mandatory dispatch proxy, or protected external effect.
- The run used a dirty working tree. Exact historical source hashes are recorded, but temporary requests/results/seals were deleted; a later clean pinned rerun is needed for a fully auditable archive.
- Only two limits were exercised. Nothing here justifies claims about the other declared limits or extrapolation past any limit.
