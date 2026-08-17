# Schedule-arithmetic result

## Verdict

PASS for the isolated arithmetic bridge.  The kernel-checked module is
`lean/AuthorityContinuity/PlanScheduleArithmetic.lean`, SHA-256
`f6f5e68b14819516afa12b996742c51b5e862d4732d947c44e2d7f17a6b664e6`.

The final module builds with the pinned Lean 4.30.0 toolchain.  It contains no
`sorry`, `admit`, custom axiom declaration, or `native_decide`.  The axiom audit
reports only the accepted allowlist `[propext, Classical.choice, Quot.sound]`;
`Classical.choice` occurs only in the finite-sum phase-derivation helper.

## Definitions and checked results

- `totalE E k` sums exposed/durable demand over every finite schedule slot.
- `priorP P s k` sums planned demand over the strict linear-order prefix
  `{t | t < s}`.
- `PhaseBound P E s k` is deliberately scoped to the current head and current
  coordinate.  It is not a universally quantified condition over every slot.
- `totalE_zero` proves that an all-zero exposure map has total exposure zero.
- `priorP_zero` proves the analogous strict-prefix fact for an all-zero plan.
- `initial_phaseBound` proves that a fresh all-zero exposure map satisfies the
  phase bound at any selected head and coordinate.
- `phaseBound_of_before_le_and_after_zero` derives the current-head phase
  bound from `E t k <= P t k` strictly before the head and `E t k = 0`
  strictly after it.  The head exposure is retained verbatim, so the lemma
  does not require the unnecessarily strong global `PhaseBound` condition.
- `E_le_P_of_partition` derives `E s k <= P s k` from the exact partition
  equation `B s k + E s k + W s k = P s k`.
- `durable_add_request_le_cap` derives `durable + q <= cap` from exactly:
  `durable = d0 + totalE E k`, the current-head phase inequality
  `totalE E k <= priorP P s k + E s k`, the envelope
  `L s k + E s k <= R s k`, `q <= L s k`, the deadline
  `d0 + priorP P s k + R s k <= cap0`, and `cap = cap0`.

The main theorem does not assume `readiness`, `promotedLoad`, `hPfits`, or the
capacity conclusion under another name.

## Retained validation

- `invocation-01-path-error.log`: first source elaboration reached Lean without
  a theorem error, but the retained-log path was rooted incorrectly.  This is
  retained rather than hidden.
- `invocation-02.log`: failed because a doc comment immediately preceded a
  `section`; the declaration order was corrected.
- `invocation-03.log`: direct `lake env lean` check, exit 0 (empty output).
- `invocation-04-lake-build.log`: package build, exit 0, 8,475 jobs.
- `invocation-05-helper-build.log`: final package build after adding the
  structural phase derivation helper, exit 0, 8,475 jobs.
- `axiom-audit-01-missing-olean.log`: retained failed audit before the package
  `.olean` had been built.
- `axiom-audit-02.log`: successful pre-helper post-build axiom audit.
- `axiom-audit-03-final.log`: successful final audit including the helper.
- `static-scan.log`: successful prohibited-term scan.
- `hashes.sha256`: source and audit-driver hashes.

## Claim boundary

This module proves only the natural-number implication once its premises are
supplied.  It does not prove that a runtime's lifecycle trace maintains the
durable equation, that `E` records every and only durable Prepare, that the
current head/cursor progresses correctly, that `L` is the actual head-group
load, or that a capacity observation remains unchanged.  Those are integration
obligations for the importing plan invariant.

The theorem is coordinatewise.  Consequently it does not need to enumerate
`Coord`; it applies to finite-coordinate models (the intended caller) and, more
generally, to any coordinate type.  Slot finiteness and a linear order are
required because `totalE` and `priorP` enumerate the schedule and its strict
prefix.
