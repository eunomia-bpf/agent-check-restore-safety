# Step 0007 full run: non-batch tentative root transport

Date: 2026-08-01 (America/Vancouver)

Scope: only `lean/AuthorityContinuity/PlanRootTransport.lean` and this
`full-run/root-transport/` evidence directory.  This run did not edit
`Plan.lean`, `PlanInvariant.lean`, `PlanExamples.lean`, the paper, or any
canonical design/story/evaluation document.

## Terminal result

The third retained single-file invocation and the fourth retained module
build both succeeded with the pinned Lean 4.30.0 toolchain:

```text
PATH=/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin:$PATH \
  lake env lean AuthorityContinuity/PlanRootTransport.lean
exit code: 0

PATH=/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin:$PATH \
  lake build AuthorityContinuity.PlanRootTransport
exit code: 0
```

Final source SHA-256:
`73a5005cbb7f1054d01e8ff0b9104251aacd7366ead9fb5bb5b46a195bbd59a6`.

Retained evidence:

- `invocation-01.log`: failed syntax/proof-engineering attempt; no theorem
  result was claimed.
- `invocation-02.log`: first successful single-file elaboration.
- `invocation-03.log`: successful elaboration after adding target-level
  rejection corollaries and explicit axiom prints.
- `invocation-04.log`: successful module build (744 jobs).
- `invocation-05.log`: source hash, theorem inventory, and forbidden-form
  scan; `FORBIDDEN_SCAN=PASS`.

## Proved bridge

### 1. Target root is computed, never supplied

`transportedRoot root tr c'` is definitionally

```text
(tr.rho c').bind root
```

The target map is therefore a function of the source root map and the actual
checked transfer only.  No theorem or checker accepts a caller-provided target
root map.

`targetCore_tentative_root_inherited` proves that every tentative claim in
the actual `Transfer.targetCore A tr allowed` has a source `c` and owner `b`
such that:

```text
tr.rho c' = some c
A.auth.status c = tentative b
transportedRoot root tr c' = root c
```

The proof consumes `Transfer.CoreValid.source_tentative` and the repository's
actual `targetStatus_tentative_iff`; it has no target-lineage premise.
`canonicalTarget_tentative_root_inherited` specializes the same result to the
actual `canonicalTarget` using `CanonicalValid.transfer.toCoreValid`.

### 2. `L` covers every tentative target claim, not only a batch

`tentativeLineageLoad A root r k` sums demand for every tentative claim whose
lineage is the exact `Option Slot` label `r`.  Quantifying over `Option Slot`
is deliberate: the theorem covers every scheduled `some s` root and also the
explicit `none` class.  `tentativeRootLoad` is the scheduled-root
specialization used by an `L_i + E_i <= R_i` envelope.

For every actual target contract, lineage label, and coordinate,
`targetCore_tentative_lineage_load_le` proves:

```text
L(targetCore A tr allowed, transportedRoot root tr, r, k)
  <= L(A.auth, root, r, k)
```

The proof first maps every target tentative member to its real source root,
then reindexes the complete target sum by actual `rho` fibers, and finally
applies `Transfer.CoreValid.fiber_demand` independently to every source
claim.  There is no selected batch in the statement or proof.

`targetCore_tentative_root_load_le` gives the required per-slot/per-coordinate
form.  `canonicalTarget_tentative_lineage_load_le` and
`canonicalTarget_tentative_root_load_le` give the same result over the actual
canonical Fork/Restore target.

This theorem establishes the missing monotone `L` transport bridge.  If a
separate source invariant supplies `L_source(s,k) + E(s,k) <= R(s,k)` and the
topology step stutters on `E` and `R`, natural-number monotonicity can derive
the target envelope.  This module intentionally does not claim or define that
larger plan invariant.

### 3. Executable target owner/root purity

`checkOwnerRootPure` is a finite Boolean checker.  Its soundness theorem
derives `OwnerRootPure`: two tentative claims with the same owner must have
equal `Option Slot` roots.

`checkTargetOwnerRootPure` instantiates that checker on the actual
`Transfer.targetCore` and its computed `transportedRoot`.  Universal
kernel-checked rejection theorems prove that it returns `false` whenever one
target owner combines either:

- `some s` and `some t` with `s != t`; or
- `some s` and `none`.

These theorems are stronger than a single executable fixture: they cover
every finite target state satisfying the displayed mixed-owner witness.

## Premise and axiom audit

The load theorem's only semantic certificate is source-side
`Transfer.CoreValid A tr`, which is the logical output of the existing actual
checker.  It does not assume target `L`, a target residual envelope, target
`WF`/`AC`, owner purity, or a caller-selected target root map.  The owner
checker soundness and rejection results do not assume `CoreValid`; they speak
directly about the computed target ledger.

The static scan found no `sorry`, `admit`, project `axiom`, `native_decide`,
or `targetRoot` argument.  Explicit `#print axioms` output reports only the
repository's accepted Lean/Mathlib dependencies:

```text
propext
Classical.choice
Quot.sound
```

There is no `sorryAx` or custom axiom.

## Claim boundary

This isolated bridge proves root inheritance and monotonicity of the complete
tentative `L` component across checked transfer/canonical targets.  It does
not by itself prove `L + E <= R`, durable-load accounting, cursor advance,
Prepare readiness, same-slot Merge admissibility, restriction transport, or
an arbitrary-trace `PlanValid` theorem.  Those remain integration obligations
for the larger Step 0007 experiment.
