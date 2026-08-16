# Implementation and Evidence Boundary

**Status:** repository truth as of 2026-08-16. This document distinguishes implemented artifacts, positively reviewed finite-model evidence, conditional refinement assumptions, and proposed runtime work so the paper never reports an abstract theorem as deployed-product safety.

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

This is selected-rule bounded executable validation, not an implementation of the complete LTS or a runtime monitor. The canonical commands and precise enumeration bounds are in `artifact/README.md`; `artifact/results/exhaustive.json` is deterministically reproduced with SHA-256 `5ae07a5505638891b4901835d4e0973a96ce6ea3e1ae202f85da565cac99a4a5`.

### Lean finite abstract-lifecycle evidence

`lean/` contains a pinned Lean 4.30.0/Mathlib 4.30.0 development over arbitrary finite carrier types. Its executable AC checker, computed restriction, exact Prepare/cleanup, ticket phases, binding persistence, terminal/epoch monotonicity, effect-coverage sum, and conditional concrete trace theorem build without proof placeholders or project-declared axioms. It now also computes exact choice/parallel Fork and replacing/live Restore targets; checks source-local transfer, preallocated-unissued fragment provenance, `rho` fiber conservation, and owner projection; and implements distinct simulation and direct Merge admissions under one full lifecycle Step/Trace.

The independent experiment verdict is positive for that finite abstract scope. A clean cached-dependency build completed 755 jobs in 10.02 seconds, and a fresh `leanchecker` replay exited zero; exact statements, controls, raw logs, and admitted foundations are retained in `lean/results/` and `docs/tmp/build-and-evaluate/step-0002-20260801T061001-0700/`. Boundary I/II, truly dynamic ID allocation, issuer approval, refined effect binding, complete mediation, aggregate sink truthfulness, and a real runtime refinement are not mechanized.

### Fixed Codex adapter evidence

`adapter/` now contains a checked, narrow runtime instantiation.  It launches
the pinned real Codex 0.146.0 App Server, owns 44 dynamic-tool callbacks, and
routes one
isolated protected sink through a separately killable SQLite-backed authority
controller.  The deterministic loopback Responses endpoint chooses the fixed
tool call; it is not the system under test and uses no live model or network.

The revision-2 C01--C20 matrix ran under four authority policies.  P3 matched
89/89 frozen decisions, and all 20 controller logs replayed under an
independently implemented transition decoder.  Across the full suite, 33 hard
worker crashes recovered in distinct processes, and no run duplicated or
bypassed an aggregate sink outcome.  Raw
App Server JSONL independently matches all 44 tool calls and 187 native forks:
80 per-run setup roots plus 107 accepted lifecycle materializations (80 fork
children, 24 restore copies, and three merge targets).  These forks do not
encode the adapter's logical ancestry.  C19 includes a canonical fixed
projection and claim map; C02
and C04 execute rather than infer their attempt-admission probes.  The complete
artifact and checker commands are in `adapter/README.md`.

This is a fixed adapter/litmus implementation, not a production monitor.
Choice/parallel, replacing/live Restore, and Merge meanings belong to the
adapter; native ephemeral children all fork the persistent seed.  The run does
not cover a crash between topology admission and native activation, App Server
or frontend death, built-in tools, direct same-user database access,
non-queryable sinks, semantic binding, or power loss.  Consequently it
validates one concrete correspondence witness under the paper's premises; it
does not discharge product-wide complete mediation or the general conditional
refinement theorem.

### Native Codex-in-Firecracker continuity evidence

The repository now also contains a separate real-KVM vertical slice. A
transparent executable preserves the ordinary Codex App Server process
boundary while placing the exact native Codex 0.147.0 binary inside a complete
Firecracker guest. The guest has no NIC or account credential; a fixed host
relay owns its only model path. At one dynamic-tool callback, the host bridge
establishes a two-way stream checkpoint, drains the model path, snapshots a
paused G1, kills and reaps its exact VMM, loads the snapshot into an independent
paused G3, arms its endpoints, resumes it, reconnects the stream, and only then
delivers the callback.

The implementation fails closed on an early client EOF, VMM death, stale
generation, replay divergence, output reordering, unbounded runner diagnostics,
unsealed input, socket-peer mismatch, or missing successful completion of the
same protected turn. A separately implemented checker joins the VMM API and
relay records, process identities, snapshot hashes, canonical client/server
commitments, App Server records, and exact lifecycle order. One fresh current-
source KVM execution produced 22 lifecycle events, 16 retained artifact hashes,
80 bridge commitments, and 352 App Server records; both VMMs were reaped and
the checker returned `{"schema":1,"valid":true}`.

This result validates one whole-process continuity mechanism. It does not yet
import a real repository, export a patch, mediate all built-in tools, run under
Firecracker jailer/cgroups, or bind the callback to the durable History/Rule
activation protocol. Full details and reproduction entry points are in
`docs/firecracker-codex-runtime.md`.

### Not implemented

There is currently no:

- ACRFence reference monitor;
- eBPF effect receipt mechanism;
- semantic fingerprint security boundary;
- production topology-aware authority monitor;
- compact structured/guarded solver for unbounded runtime contracts;
- bounded transition-schedule and mutation explorer;
- production integration that prevents the modeled violations across every
  effect path and topology crash window.

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

It does not implement the compact PB/ZDD solver.  The canonical finite
topology/certificate layer exists in Lean, and the separate `adapter/` now
implements a fixed crash-atomic effect-ticket controller/ledger gate for the
controlled suite, not crash-atomic topology activation, the full guarded-
contract algorithm, or a production monitor. New
components should be added as separate directories only when one clean command
can exercise them; scaffolding an empty architecture would create false
evidence.

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

1. Complete the ethics-reviewed public-trajectory census if access is granted;
   the existing schema/pilot work establishes telemetry gaps but not workload
   prevalence.
2. Mechanize Boundary I/II if page and proof budget permit, independently of
   the completed lifecycle/topology theorem.
3. Implement the compact guarded-contract oracle with a checkable violating-
   configuration certificate and retain the unguarded cotree fast path before
   measuring latency and safe-history rejection.
4. Extend the dispatch-owning prototype to crash-atomic topology activation
   and a mandatory tool/network proxy before making a production complete-
   mediation claim.

The runtime adapter should use explicit App Server/SDK lifecycle identifiers where possible. Optional hooks can prototype event capture, but they are not the trusted boundary unless all bypasses are closed. eBPF inference is lower priority than an explicit, proof-aligned dispatch path.
