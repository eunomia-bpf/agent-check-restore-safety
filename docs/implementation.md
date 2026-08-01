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

`artifact/` now contains a dependency-free Python authority-continuity model, 24 unit tests, a deterministic exhaustive explorer, and a machine-readable v5 result. It currently checks:

- universal-frontier AC against the componentwise-need formulation on 1,312 owner-support well-formed states (a separate 2,816-state raw algebra scan is diagnostic only);
- Reserve against branch headroom for 6,180 demands over 730 owner-supported safe source states;
- batch admission against correlated residual membership for 17,658 batches;
- the exact headroom-box factorization criterion on all 730 safe sources (296 rectangular and 434 nonrectangular);
- 4,067 accepted residual prefixes and 103,785 successor-membership instances of the derivative law, with an expanded parent box that covers every queried sum;
- the bounded knowledge checker against profile intersection for all nine batches in the fixed two-state fiber;
- safety and downward closure for 2,060 single-claim promotions;
- inclusion maximality against 22,246 safe downward-closed restrictions;
- exact frozen-guard membership on 2,060 repairs and 11,142 configurations;
- 6,312 ordered disjoint promotion pairs in both explicit and guarded representations;
- the higher-order \(U_{2,3}\) representation witness, frozen/dynamic withdrawal distinction, OR-lineage live-restore transport, and final-owner-support positive/negative serialization cases;
- an actual fresh-Reserve replace/live indistinguishability litmus and safe-choice/unsafe-escape witness;
- an eight-state, 22-edge crash/retry/revoke ticket graph covering Prepare, Dispatch, Retry, Crash, Settle, cancellation, sealed completion after revocation, rejection of tentative claims on tombstoned branch epochs, and rejection of closed-epoch name reuse; and
- 26 target-frontier simulations across replace/live restore and choice/parallel fork, preserving receipts and prepared/uncertain tickets.

This is selected-rule bounded executable validation, not an implementation of the complete LTS, a proof assistant development, or a runtime monitor. The canonical commands and precise enumeration bounds are in `artifact/README.md`; `artifact/results/exhaustive.json` is deterministically reproduced with SHA-256 `5ae07a5505638891b4901835d4e0973a96ce6ea3e1ae202f85da565cac99a4a5`.

### Not implemented

There is currently no:

- ACRFence reference monitor;
- eBPF effect receipt mechanism;
- semantic fingerprint security boundary;
- production topology-aware authority monitor;
- compact structured/guarded solver for unbounded runtime contracts;
- bounded transition-schedule and mutation explorer;
- Lean model or proof;
- runtime integration that prevents the modeled violations.

The paper must use future tense or an explicit placeholder for all of these until an artifact and command reproduce them.

## 3. Current artifact boundary and next layer

The current flat Python artifact intentionally mirrors the paper equations and stores configurations explicitly for at most three branches. It implements the finite mathematical layer:

```text
artifact/
  authority_continuity.py       # state, residuals, guarded repair, litmus operations
  explore.py                    # deterministic bounded enumeration and JSON report
  test_authority_continuity.py  # fixed theorem and counterexample checks
  results/exhaustive.json       # checked-in reproducible result
```

It does not implement the compact PB/ZDD solver, crash-atomic ledger, lifecycle controller, effect gate, or proof assistant development described by the paper. Those components should be added as separate directories only when one clean command can exercise them; scaffolding an empty architecture would create false evidence.

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

## 5. Remaining implementation order

1. Mechanize typed vectors, claim partition, headroom, correlated residual derivatives, exact promotion guards, support cleanup, and the small trace invariant in Lean 4.
2. Add a bounded transition/mutation explorer for claim duplication, stale epochs, dispatch-before-Prepare, dynamic guards, wrong lineage transport, and owner-tombstoning serialization.
3. Implement a compact guarded-contract oracle with a checkable violating-configuration certificate and retain the unguarded cotree fast path.
4. Implement one dispatch-owning adapter or mandatory tool proxy that durably assigns branch epochs and executes Prepare before every protected call.
5. Only then measure admission latency, durable writes, contention, and safe-history rejection against split-all, parent escrow, and transaction-only baselines.

The runtime adapter should use explicit App Server/SDK lifecycle identifiers where possible. Optional hooks can prototype event capture, but they are not the trusted boundary unless all bypasses are closed. eBPF inference is lower priority than an explicit, proof-aligned dispatch path.
