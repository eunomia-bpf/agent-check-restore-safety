# Real preflight result: finite shared-prefix admission

Date: 2026-08-03

## Verdict

**PASS, dependency-only.** The preflight establishes that the planned
declarative and executable encodings can be made independent and can reproduce
the paper's exact finite shared-prefix obstruction in the real pinned Lean
environment. It is not evidence for any general theorem in the paper.

## Frozen source and environment

- Source:
  `lean/AuthorityContinuity/AgentHistoryAdmission/FiniteCore.lean`
- Source SHA-256:
  `753e2d814cc8a35e3cb4ae3cc307fc228ccf011f6293d8cd4989c68f0bdb766e`
- Repository parent commit:
  `dd1605b32144a7b557baa7677c9581c0e30b3d3f`
- Lean:
  `4.30.0`, commit `d024af099ca4bf2c86f649261ebf59565dc8c622`
- Lake:
  `5.0.0-src+d024af0`
- Elan:
  `4.2.3`, commit `b6cec7e10`
- Mathlib:
  repository-pinned `v4.30.0`

Authoritative command, run from `lean/`:

```sh
ELAN_HOME=/home/will/.cache/agent-history-elan \
PATH=/home/will/.cache/agent-history-elan/bin:/usr/local/bin:/usr/bin:/bin \
lake env lean AuthorityContinuity/AgentHistoryAdmission/FiniteCore.lean
```

The final timed run completed with:

```text
wall_seconds=7.69
max_rss_kb=6773696
exit_status=0
```

The local raw log is
`docs/tmp/research-experiment-design-20260803T160000Z/raw/preflight-lean.log`,
SHA-256
`3255b362f28f32615d559d5ccfc4dff27cb72e58be424e13428bb4356cc15444`.
Raw `*.log` files are intentionally git-ignored.

## What was actually checked

The source constructionally derives resolved candidates rather than accepting
hand-written traces:

- an instance supplies promised outcomes, raw linearizations, an
  occurrence-to-cell registry, an initial receipted-cell set, a separate
  durable authority prefix, a cell-to-label map, and a finite prefix-closed
  authority policy;
- the resolver scans a raw word left to right, emitting `Fresh` on the first
  unreceipted occurrence of a semantic cell and `Alias` thereafter;
- `allCandidates` is derived only from promised outcome linearizations through
  that resolver;
- `raw_resolve` proves that resolution preserves the registered occurrence
  word;
- `authorityWord` counts only `Fresh` cells and maps them through the authority
  label function.

The two answers are independent:

- `SemanticAns` enumerates every subfamily of the constructionally derived
  candidate family and directly checks nonemptiness, history fidelity, policy
  safety at every generated prefix, and persistent compatible-outcome
  coverage. It does not invoke `B0`, `Phi`, pruning iteration, or the bounded
  fixed point.
- `CompilerAns` validates policy prefix closure, computes the individually safe
  base `B0`, applies the executable `Phi` from that base, and decides from the
  bounded descending result.

The literal paper fixture is \(X\parallel(Y\oplus Z)\) with outcome
linearizations `xy,yx` and `xz,zx`, empty receipt/durable prefixes, and
\(\mathcal A=\operatorname{Pref}\{yx,xz\}\). Kernel-checked closed propositions
establish:

- the four resolved candidate completions are exactly `xy`, `yx`, `xz`, and
  `zx`, indexed by their outcomes;
- \(B_0=\{yx,xz\}\);
- at prefix `Fresh x`, the left outcome remains causally compatible but has no
  supporting left completion, so `xz` is removed;
- after round one, the root remains compatible with the right outcome but has
  no right support, so `yx` is removed;
- the pruning cardinalities are exactly `[2,1,0]`;
- `CompilerAns = SemanticAns`, and both are `reject`.

No `sorry`, tactic `admit`, project `axiom`, `unsafe`, or placeholder occurs.
`Ans.admit` is only an answer constructor.

## Review history

The first implementation produced the correct `[2,1,0]` numbers under a
stronger toy condition that omitted the paper's `Compat(raw(z))`; it was
rejected and replaced.

The next implementation matched the fixture but still accepted
caller-supplied resolved candidates and left policy prefix closure implicit.
An independent semantic attack returned **FAIL**. The source was then revised
to derive all candidates through a receipt-aware resolver, check policy prefix
closure, restore the literal \(\operatorname{Pref}\{yx,xz\}\) instance, and
prove the second deletion's root cause.

Two independent final read-only reviews returned **PASS**. The reviewer that
issued the semantic FAIL explicitly confirmed that all four blockers were
removed and independently replayed the Lean file with exit status 0.

## Interpretation and next decision

The preflight supports only the dependency hypothesis that the real Lean
toolchain and non-circular encoding route are viable. It does **not** prove:

- a general resolver theorem beyond the displayed finite functions;
- fixed-point stabilization or greatest-realization equivalence for arbitrary
  inputs;
- declarative/executable history-derivation soundness and completeness;
- any P/I/E/C or incidence lower bound;
- natural-genesis reachability;
- `AgentSec` preservation or arbitrary finite-prefix closure;
- ideal/kernel matching, crash refinement, or weak bisimulation;
- the paper's assembled Agent Security-State Characterization.

Decision: proceed to the frozen decisive modules. Do not change the paper on
the strength of this preflight alone.
