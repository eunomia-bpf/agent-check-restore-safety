# Plan-invariant first closure report

Date: 2026-08-01

Frozen source:

- `lean/AuthorityContinuity/PlanInvariant.lean`
- SHA-256: `b0f6f2dc48de118604765a5e4d03cda4423e3f7b17e0ef4bc4bd7a75e1161f02`
- size: 1,083 lines, 46,656 bytes

## Outcome

The first multi-slot, multi-Prepare vertical gate is kernel checked.  It is a
Prepare-only closure theorem, rather than closure of the eventual full
Fork/Restore/Prepare/restriction/Merge grammar.

The module now derives the real lifecycle `PrepareOK` capacity guard from a
source controller invariant, constructs the repository's real `Step`, computes
the exact post-Prepare controller, preserves the complete controller invariant,
and iterates this result over arbitrary finite authoritative Prepare traces.

No theorem accepts any of the following as a premise:

- the target controller's validity;
- the target lifecycle's well-formedness or authority continuity;
- `hPfits` or an equivalent durable-plus-planned-load capacity oracle;
- `hbatchP` or an equivalent current-request bound;
- a separately certified head phase/readiness proposition; or
- a proposed post-state/cursor supplied by the caller.

## Controller data and semantics

`PlanData` records:

- a monotone CAS `version`;
- baseline durable load `d0` and capacity `cap0`;
- a finite linearly ordered set of schedule slots;
- an independent claim-to-root-slot ledger `rootSlot`;
- the remaining selected batch;
- per-slot reservation `R`, planned load `P`, and exposed durable load `E`.

The executable scheduler computes:

- `rootRemaining s`: remaining batch claims rooted at `s`;
- `ownerGroup A p s b`: the remaining claims at `s` tentatively owned by `b`;
- `activeGroups`: all nonempty `(slot, owner)` groups;
- `firstGroup`: the lexicographically first active group;
- `cursor`: the slot projection of `firstGroup`; and
- `headGroup`: the exact current owner group.

The cursor is not stored controller state.  It is recomputed from the real
lifecycle and remaining batch after every transition.

`L A p s k` sums every actual tentative claim rooted at `s`, not merely claims
in the selected batch.  Thus unrelated, non-batch authority is included in the
reservation envelope.  An unrelated tentative owner may have `rootSlot = none`;
`remaining_rooted` roots only selected batch claims, while `owner_root_pure`
requires claims of one tentative owner to agree on their optional root.

The exact post-controller `afterPrepareGroup`:

- increments `version` by one;
- executes the repository's actual `prepareState`;
- filters `remaining` by the claims that are actually tentative in that target,
  thereby accounting for deterministic cleanup; and
- increments `E` at the source first-group slot by the exact promoted batch
  load.

## Preserved invariant

`PlanData.Valid A p` contains:

- lifecycle capacity equals `cap0`;
- every remaining claim is tentative and rooted in a declared slot;
- tentative-owner root purity;
- every `some` root belongs to the declared schedule;
- `E` and `P` are zero outside the finite schedule;
- `DurableEq`: `durableLoad = d0 + sum E`;
- `Envelope`: `L(s,k) + E(s,k) <= R(s,k)`;
- `Deadline`: `d0 + priorP(s,k) + R(s,k) <= cap0(k)`;
- `BatchBound`: `B(s,k) + E(s,k) <= P(s,k)`; and
- `CursorPhase`: exposure in every declared slot after the computed cursor is
  zero.

An earlier draft stored `HeadPhaseBound` as a separate validity field.  That
field was removed.  `Valid.derived_head_phase_bound` now derives it from
`BatchBound`, `CursorPhase`, and zero exposure outside the schedule.  This
removes a readiness proposition that otherwise risked becoming an oracle.

## Non-circular readiness

The readiness path is:

1. nonempty `remaining` implies a computed `firstGroup`;
2. the current `headGroup` is nonempty and consists of actual tentative claims;
3. `headGroup` is a subset of all tentative root claims in the current slot;
4. the derived head phase bound localizes total durable exposure to prior slots
   plus the current `E` row;
5. `Envelope`, `Deadline`, `DurableEq`, and capacity equality imply the actual
   `promotedLoad <= capacity` guard; and
6. the executable assignment checker supplies the remaining `PrepareOK` fields.

The resulting theorems are:

- `current_group_promotedLoad_le_capacity`;
- `current_group_prepare_ok`; and
- `current_group_actual_step`.

The last theorem reaches `Step.core (CoreStep.prepare ...)` and the repository's
sole exact `prepareState`.

## Exact Prepare preservation

The proof handles real cleanup rather than assuming that only the promoted set
changes:

- target tentative root claims are a subset of source tentative root claims
  minus `headGroup`;
- target remaining root batches are a subset of source batches minus
  `headGroup`;
- the residual current-slot live load plus the promoted load is at most the old
  live load;
- the residual current-slot batch load plus the promoted load is at most the old
  batch load; and
- active target groups form a subset of active source groups.

These facts prove:

- exact `DurableEq` preservation using `preparedCore_durableLoad` and
  `rawPromotion_durableLoad_eq_promotedLoad`;
- `Envelope` preservation;
- `BatchBound` preservation;
- monotone recomputation of the first slot and `CursorPhase` preservation; and
- all metadata/root/zero-outside/deadline fields.

They are assembled by `afterPrepareGroup_preserves_valid`.

## Authoritative CAS and iteration

`checkVersion` is an executable Boolean equality check over the durable plan
version, and `checkVersion_sound` proves that an accepted offered version equals
the current version.

The paper-facing `PreparePlanned` relation accepts only:

- source lifecycle `LWF`;
- source `PlanData.Valid`;
- nonempty remaining work;
- successful executable version CAS; and
- successful executable assignment check.

Its target is definitionally `advancePrepare`, not a caller-proposed state.
It proves:

- the offered version is current;
- the transition is a real lifecycle `Step`;
- target `Valid`;
- target `LWF` and `AC`, given source `AC`; and
- target version equals source version plus one.

`PlannedPrepareTrace` is the reflexive-transitive closure of existentially
labelled `PreparePlanned` edges.  The module proves:

- `planned_prepare_trace_preserves`: arbitrary finite traces preserve `LWF`,
  `AC`, and the full controller invariant;
- `planned_prepare_trace_projects`: arbitrary finite controller traces erase to
  traces of the sole lifecycle `Step` relation;
- version monotonicity; and
- remaining-batch cardinality monotonicity.

Every enabled Prepare strictly decreases `remaining.card`.  Consequently,
`plannedPrepareEdge_wellFounded` proves the reverse execution relation is well
founded under that measure.  `two_prepare_gate` separately packages a concrete
two-round vertical theorem: after the first checked Prepare, its derived target
invariants justify a second checked Prepare, and both transitions project to
real lifecycle steps.

## Verification record

All failed and successful attempts were retained under `invariant/`.

Important milestones:

| Invocation | Result | Milestone |
|---|---:|---|
| 001 | fail | direct Lean invocation lacked built dependency object |
| 002 | fail | initial product-order and proof elaboration errors |
| 003 | pass | base controller API |
| 006 | pass | derived readiness, real `PrepareOK`, real `Step` |
| 007 | fail | sole remaining finite-sum update goal |
| 008 | pass | exact total-`E` update |
| 009 | pass | exact durable equation preservation |
| 010 | pass | stored head-phase field removed and derived structurally |
| 012 | pass | exact cleanup-aware envelope preservation |
| 014 | pass | active-group subset and cursor/phase preservation |
| 016 | pass | batch-bound preservation |
| 017 | pass | complete target `Valid` preservation |
| 018 | pass | CAS, authoritative relation, RTC projection/preservation, two rounds |
| 019 | pass | strict progress and well-foundedness; final targeted build |
| 020 | pass | full `lake build` (all jobs already cached) |

Final targeted command:

```text
PATH=/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin:$PATH \
  lake build AuthorityContinuity.PlanInvariant
```

The final build completed successfully.  `#print axioms` reports only the
standard allowlist `propext`, `Classical.choice`, and `Quot.sound` for the main
readiness, actual-step, full-validity, RTC, termination, and two-Prepare
theorems.  A static scan found no `sorry`, `admit`, custom `axiom`, or
`native_decide`.  `git diff --check` passed.

## Honest boundary and next gates

This module closes an arbitrary-length multi-slot **Prepare-only** gate.  It
does not yet establish preservation of this richer invariant across the entire
accepted positive grammar.

Still deferred:

- initialization/checking that constructs `Valid` from an external plan;
- root-ledger transport across canonical Fork/Restore;
- computed restriction/Revoke transport and withdrawal accounting;
- checked owner-pure same-slot Merge transport;
- integration of those operations into the authoritative RTC grammar;
- a concrete finite runtime serialization and atomic storage implementation of
  the logical CAS; and
- runtime/trace evaluation beyond the formal executable examples.

The important change in classification is that multi-round Prepare is no
longer a deferred proof idea: it is now an arbitrary finite kernel-checked
subgrammar with exact cleanup, authoritative versioning, real lifecycle
projection, safety preservation, and termination.  The project should not yet
claim full positive-grammar closure until the deferred transport rules preserve
the same invariant.
