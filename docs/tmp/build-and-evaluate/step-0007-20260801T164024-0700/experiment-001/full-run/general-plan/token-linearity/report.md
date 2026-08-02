# Discrete token/origin linearity extension

Date: 2026-08-01 (America/Vancouver)

## Outcome

Implemented a new, isolated Lean module:

- `lean/AuthorityContinuity/PlanTokenLinearity.lean`

The module closes the zero-demand duplication hole with an immutable discrete
token ledger rather than another demand inequality. It covers checked
Canonical operations, Prepare, simulation/direct Merge, Restriction, actual
Revoke, checkpoint, and every existing ticket/recovery phase. It also defines
an arbitrary finite token-aware trace, proves preservation, erases it to the
existing `PositiveTrace`, and consequently projects it to the repository's
sole lifecycle `Step` trace.

No existing plan module and no frozen `ZeroDemandDuplication.lean`
counterexample was edited. In particular, the duplicate theorem in
`PlanInvariantPrepare.lean` was not touched by this work. No commit was made.

## Model

`TokenLedger` contains:

- `initial : Finset Token`: the tokens minted before plan execution;
- `origin : Claim -> Option Token`: a claim-to-immutable-origin map; and
- `disposition : Token -> TokenDisposition`, where the three dispositions are
  `remaining`, `prepared`, and `withdrawn`.

The semantic fibers are computed from real controller data:

- the current fiber filters the actual `plan.remaining` set by `origin`; and
- the binding fiber filters actual operations by
  `(lifecycle.opClaim e).bind origin`.

`LinearValid` requires both every current claim and every durable operation
binding to be covered by an initial token. For each initial token it requires
current-fiber cardinality at most one, operation-binding-fiber cardinality at
most one, mutual exclusion of those two fibers, and exact agreement between
the stored disposition and the disposition computed from the two actual
fibers.

`LinearValid.token_trichotomy` makes the accounting statement precise. Every
initial token is exactly one of:

1. remaining: current-cardinality 1 and binding-cardinality 0;
2. prepared: current-cardinality 0 and binding-cardinality 1; or
3. withdrawn: both cardinalities 0.

No positivity premise and no demand coordinate occurs in this result.

## Executable checker

`TokenState.checkLinear` is a finite Boolean checker for all fields of
`LinearValid`. `TokenState.checkLinear_sound` proves checker soundness. The
checker rejects untracked current claims, untracked durable bindings,
same-token current duplication, same-token durable binding duplication,
simultaneous current/prepared witnesses, and an incorrect disposition.

The important admission boundary is explicit: the Canonical and both Merge
checkers are the existing operation checker conjoined with a **full finite scan
of the deterministically computed target token state**. This is not a theorem
that derives target token linearity solely by semantic transport from source
linearity. It is a verified executable reference-monitor design: the target is
not caller supplied, and `checkLinear_sound` turns the successful target scan
into the semantic invariant.

No target `LinearValid` proposition is accepted as a premise.

## Operation coverage

### Canonical and Merge

`transportedOrigin` follows the transition's actual `rho`: if
`rho c' = some c`, the target claim receives the immutable token of source
claim `c`; otherwise the old origin is retained. The latter retains origins
for stable durable bindings outside the transfer domain. The resulting ledger
is reclassified against the computed target controller.

The generic Canonical checker covers choice fork, parallel fork, replacement
restore, and live restore. The following theorems establish that two target
remaining claims carrying one token must be equal:

- `checkedCanonical_same_token_eq`;
- `checkedSimulationMerge_same_token_eq`; and
- `checkedDirectMerge_same_token_eq`.

Thus no choice/fork mode can duplicate one token. If a workload intentionally
needs a quantitative split into independently preparable effects, it must mint
several distinct tokens before entering the plan grammar.

### Prepare

`advancePrepare` invokes the existing computed `PlanData.advancePrepare`, so
the transition uses the real head group, actual assignment, actual
`prepareState`, and actual unsupported-owner cleanup. It keeps the origin map
and recomputes dispositions from the exact target.

- `checkedPrepare_head_token_prepared` proves that a checked head token becomes
  prepared and has an actual durable `opClaim` binding.
- `checkedPrepare_distinct_tickets` proves that two target operations whose
  claims have the same token are the same operation.
- `checkedPrepare_cleanup_withdrawn` classifies absence of both actual target
  witnesses as withdrawal.

### Restriction and Revoke

Restriction and actual grant Revoke keep the origin map and reclassify the
ledger from their computed lifecycle/plan targets.
`checkedRestriction_withdrawn` and `checkedRevoke_withdrawn` prove computed
withdrawal from absence of both current and durable witnesses; neither accepts
a caller-asserted withdrawal set.

### Checkpoint and ticket/recovery phases

Checkpoint is literal state identity. Ticket dispatch, retry, crash, and
settle keep the complete ledger and plan version definitionally unchanged.
`ticket_preserves_linearity` uses the existing
`ticketStep_binding_eq` theorem, so moving a ticket through phases or into a
receipt preserves the stable actual `opClaim` fiber.

## Unified grammar and arbitrary histories

`TokenPositiveStep` mirrors the existing positive grammar. Every mutating
constructor wraps the corresponding existing planned relation and requires a
successful executable token scan of its exact target. Boolean-to-relation
bridge theorems are supplied for Prepare, Canonical, Restriction, Revoke, and
both Merge modes.

The main history results are:

- `TokenPositiveStep.preserves_safe`;
- `token_positive_trace_preserves` for arbitrary reflexive-transitive
  histories;
- `token_positive_trace_projects`, which erases the ledger to the existing
  `PositiveTrace`;
- `token_positive_trace_projects_actual`, which yields the existing
  `AbstractTrace` over actual `Step` transitions;
- `token_positive_trace_version_mono`; and
- `token_positive_trace_initial_eq`, which proves that no transition mints a
  token after plan creation.

This establishes a conservative checked sublanguage, not a converse theorem
that every raw runtime `Step` passed the checker.

## Zero-demand regression

The local closed fixture reproduces the frozen counterexample's essential
shape with one source token and a zero-demand `parallelFork` into two claims.
Kernel evaluation proves:

- `source_token_check_accepts`: the source token state passes;
- `base_plan_check_accepts`: the old `checkCanonicalPlan` returns `true`;
- `zero_demand_parallelFork_rejected`: the old checker is `true` while the
  combined token checker is `false`; and
- `duplicated_token_fiber_cardinality`: the unchecked computed target fiber
  has cardinality exactly 2.

These proofs use `decide`, not `native_decide`, so the axiom audit contains no
native-code evaluation axiom.

## Validation

Executed from `lean/`:

```text
lake env lean AuthorityContinuity/PlanTokenLinearity.lean
```

Result: exit 0.

```text
lake build AuthorityContinuity.PlanTokenLinearity
```

Result: `Build completed successfully (8491 jobs)`; warnings are existing or
unused-section-variable/simp linter warnings, with no elaboration error.

The module prints axiom dependencies for the checker soundness, exact
trichotomy, Canonical/Prepare/Merge/Restriction results, ticket preservation,
RTC preservation/projection, initial-token conservation, and the zero-demand
negative fixture. Every printed theorem depends only on:

```text
propext, Classical.choice, Quot.sound
```

Static scans for whole-word `sorry`, `admit`, `axiom`, or `constant`, and for
`native_decide`, `unsafe`, or `partial`, returned no matches in the new module.

## Honest boundary and remaining work

1. Canonical/Merge/Prepare/drop preservation is checker-enforced by scanning a
   finite computed target. A future strengthening could prove more atoms by
   source-only semantic transport and retain the target scan as executable
   validation, but that stronger derivation is not claimed here.
2. `checkVersion` remains pure Boolean equality in a sequential model. This is
   not a proof of an atomic, durable, linearizable runtime CAS under concurrent
   agents.
3. Trace projection is one-way. Runtime integration still needs an adapter or
   reference monitor showing that Claude/Codex-style tool actions cannot bypass
   the checked grammar.
4. Tokens establish logical one-use scheduling/binding. They do not by
   themselves prove exactly-once physical effects in an external service;
   stable operation identities, idempotency, and reconciliation remain runtime
   obligations.
5. There is deliberately no dynamic token mint in this grammar. Quantitative
   splitting is represented by pre-minting multiple tokens. Choice or topology
   fork can transport those tokens but cannot duplicate one.
6. The grammar has the same scope boundary as the existing `PositiveStep`:
   Reserve and arbitrary raw `Step` transitions are not included.
