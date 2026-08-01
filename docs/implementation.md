# Implementation and Evidence Boundary

**Status:** repository truth as of 2026-07-31. This document distinguishes implemented artifacts, legacy evidence, and proposed work so the paper never reports a plan as a result.

## 1. Branch and paper source of truth

- `main` is the active Git branch.
- `origin/overleaf-2026-08-01-0626` diverges from an older common ancestor. Its unique commit contains an older claim-heavy `main.tex`, including unimplemented ACRFence language and incorrect author metadata. It must not be merged or cherry-picked wholesale.
- The root `main.tex` is a legacy four-page ACRFence extended abstract and remains useful only as an evidence seed.
- The current theory paper lives under `docs/paper/`. Once created, that directory is the sole submission source of truth.

## 2. What exists now

### Legacy executable evidence

The repository contains Python/MCP scenarios for:

- Action Replay: restore a conversation/session and observe whether a regenerated idempotency key leads to a duplicate transfer or cloud action;
- Authority Resurrection: restore a session that still contains a one-use token and compare stateless, synchronous stateful, and asynchronous stateful validation.

Raw JSON results are retained under `experiments/results/` and `poc/results/`. The defensible aggregate evidence from the audited files is:

- Action Replay transfer scenario: 10/10 duplicate/key-change trials in the recorded run;
- Action Replay cloud scenario: 10/10 duplicate trials in the recorded run;
- strict no-restore baseline: 0/10 duplicates;
- deletion token scenario: stateless 2/2, stateful synchronous 0/2, stateful asynchronous 0/2;
- payment token scenario: stateless 0/2, stateful synchronous 1/2 anomalous success, stateful asynchronous 0/2.

These are motivating observations, not a statistical benchmark. The session mechanism truncates or resumes conversation JSONL; it is not an OS process checkpoint. The prompt explicitly asks the model for a fresh UUID, so it demonstrates a feasible lifecycle counterexample, not inevitable nondeterminism. Documentation and the old paper also disagree on whether the local model was Qwen3-32B or Qwen3-Next-80B; the new paper must not name a model until the raw invocation is reconstructed.

### Legacy paper assets

- `img/fig-sequence.pdf` illustrates the Action Replay trace.
- `docs/framework-survey.md`, `docs/attack-scenarios.md`, and `docs/experiments.md` contain useful observations but are research diaries with repeated and stale versions.
- The root `references.bib` has useful rollback and agent citations but is not a verified bibliography for the new paper.

### Finite executable validation

`artifact/` now contains a dependency-free Python authority-continuity model, six unit tests, a deterministic exhaustive explorer, and a machine-readable result. It currently checks:

- universal-frontier AC against the componentwise-need formulation on 2,816 states;
- safety and downward closure for 3,428 single-claim maximal-support promotions;
- inclusion maximality against 27,142 safe downward-closed restrictions;
- 13,680 ordered pairs of disjoint batched promotions for confluence;
- the replace/live indistinguishability litmus and the safe-choice/unsafe-escape witness.

This is bounded executable validation, not a proof assistant development or runtime monitor. The canonical commands and precise enumeration bounds are in `artifact/README.md`; `artifact/results/exhaustive.json` is deterministically reproduced.

### Not implemented

There is currently no:

- ACRFence reference monitor;
- eBPF effect receipt mechanism;
- semantic fingerprint security boundary;
- topology-aware authority monitor;
- structured choice/parallel incremental admission checker;
- bounded transition-schedule and mutation explorer;
- Lean model or proof;
- runtime integration that prevents the modeled violations.

The paper must use future tense or an explicit placeholder for all of these until an artifact and command reproduce them.

## 3. New minimal artifact

The CSF paper needs a small artifact whose code mirrors the mathematics:

```text
artifact/
  checker/          # structured and general-frontier need/deficit checker
  explorer/         # bounded lifecycle schedules and mutation counterexamples
  litmus/           # deterministic JSON scenarios
  lean/             # core state, transitions, invariant, and theorems
  tests/            # unit/property tests
```

The trusted core should accept explicit, typed facts rather than ask an LLM to infer authorization:

- grant ID, epoch, and capacity vector;
- globally unique claim ID and effect binding;
- lifecycle operation and structured topology witness;
- staged, uncertain, or escaped effect status;
- durable selection, abort, merge, revocation, and receipt records.

An LLM may propose labels outside the TCB. The deterministic monitor must reject missing or ambiguous bindings.

## 4. Reproducibility contract

Each reported result must identify:

- the exact artifact revision;
- one command that produces it;
- the input scenario or generated seed;
- the raw machine-readable output;
- whether the result is proved, model-checked, simulated, or observed in a real runtime.

No number moves into the paper from `docs/experiments.md` alone. It must be recoverable from raw results or a fresh command. Expected output in a README is not evidence.

## 5. Implementation order

1. Implement the scalar structured checker and the six separation litmus tests.
2. Add vector grants and property tests comparing the recursive checker with explicit frontier enumeration.
3. Add the general conflict-graph checker and a reduction-generated hardness sanity suite.
4. Mechanize the state split, reserve/escape/abort/restore rules, invariant preservation, and minimal-deficit arithmetic.
5. Only then integrate one or two runtime adapters. Prefer explicit lifecycle hooks over eBPF inference.

This order gives useful counterexamples and proof feedback before any large runtime engineering effort.
