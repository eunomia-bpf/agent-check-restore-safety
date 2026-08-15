# Codex authority-continuity adapter

This directory contains the fixed RQ3 experiment.  It launches the pinned real
Codex App Server, grounds histories in native `thread/fork` IDs, owns one
experimental dynamic-tool callback, and keeps that callback pending while a
separate SQLite-backed controller worker is hard-killed and restarted.  The
model endpoint and protected sink are deterministic local fixtures; the run
does not contact a live model or a production service.

The directory also contains a separate, explicit live-account system path:
`python -m adapter.codex_runtime_demo`. That runner uses the account selected by
`codex login`, a real model, the Go control daemon, and the independently
durable Go payment service. The fixed experiment above remains deterministic;
ordinary adapter tests never opt into the logged-in account.

The scientific boundary is narrow and intentional.  Codex supplies native
history IDs, exact fork boundaries, and the real `item/tool/call` seam.  The
adapter supplies the choice/parallel meaning of a fork, replacing/live restore,
merge projections, authority state, stable effect tickets, and the isolated
authenticated sink.  The experiment therefore tests a concrete adapter
instantiation, not native Codex Restore/Merge semantics or product-wide
complete mediation.

## Reproduce

From the repository root:

```bash
python -W always::ResourceWarning -m unittest discover -v adapter
python -m adapter.check_results \
  --suite adapter/litmus.yaml \
  --oracle adapter/oracle.yaml \
  --input adapter/results/litmus.json \
  --output adapter/results/check.json

adapter_run_dir="$(mktemp -d)"
python -m adapter.codex_litmus \
  --suite adapter/litmus.yaml \
  --runtime-lock adapter/runtime-lock.json \
  --raw-dir "$adapter_run_dir/raw" \
  --output "$adapter_run_dir/litmus.json" \
  --workspace .
python -m adapter.check_results \
  --suite adapter/litmus.yaml \
  --oracle adapter/oracle.yaml \
  --input "$adapter_run_dir/litmus.json" \
  --output "$adapter_run_dir/check.json"
```

Run the real-model system path only when account use is intended:

```bash
make runtime-codex-demo
```

It registers one strict dynamic tool, keeps its callback pending while the Go
control process is replaced, recovers a payment whose first response was lost,
and checks two deliveries but one durable commit. The evidence directory is
printed at completion. It never copies control API tokens into that directory.

The first two commands test the implementation and verify the retained run;
the remaining commands create and check a fresh run.  The runner refuses an
existing raw directory so a prior artifact cannot be silently overwritten.
The runtime lock
pins Codex 0.146.0 and its executable SHA-256.  The first command includes a
real App Server boundary test; the full runner also performs a C03
remote-success-before-controller-commit preflight unless `--skip-preflight` is
explicitly supplied after a retained preflight has passed.

## Separation and evidence

- `litmus.yaml` contains only C01--C20 operation streams.
- `oracle.yaml` was frozen separately.  Only `check_results.py` imports it.
- `controller.py`, `worker.py`, and `sink.py` cannot import the oracle or
  independent replay checker; a test enforces this separation.
- `replay.py` reconstructs P3 semantic state from strict deltas and verifies
  the event hash chain plus final state/head anchors.
- `app_server.py` retains raw bidirectional JSONL.  The checker cross-checks
  summarized callbacks and history IDs against that independent capture.
- Every case has isolated controller and sink databases under `results/raw/`.

The retained run contains 80 policy/case executions, 44 real dynamic-tool
callbacks, 33 injected `SIGKILL` worker crashes, and 187 native thread forks:
80 per-run setup roots and 107 accepted lifecycle materializations (80 fork
children, 24 restore copies, and three merge targets).  Logical ancestry is
adapter metadata rather than a native Codex relation.
P3 matches all 89 frozen request decisions across C01--C20, all 20 event logs
replay, and no P3 run has an unsafe acceptance, unmediated sink outcome, or
duplicate aggregate effect.  O0 and O1 each retain the three frozen mixed-label
fibers; O2 retains none.  `results/check.json` is the authoritative compact
verdict; `results/litmus.json`, raw JSONL, and SQLite files retain its evidence.

These deterministic cases are correspondence/correctness evidence, not a
frequency estimate, latency benchmark, or proof for arbitrary runtime paths.
Frontend/App Server death, built-in shell/MCP/web tools, dishonest or
non-queryable sinks, natural-language effect binding, and power-loss durability
remain outside scope.
