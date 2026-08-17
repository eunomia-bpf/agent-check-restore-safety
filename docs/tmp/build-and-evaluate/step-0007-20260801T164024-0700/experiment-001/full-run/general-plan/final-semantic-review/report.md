# Frozen promotion-plan suite: independent adversarial semantic review

Date: 2026-08-01 (America/Vancouver)

## Verdict

**FAIL as a buildable frozen suite; MIXED as a semantic result.**

- **Build: FAIL.** `lake build AuthorityContinuity` fails because
  `PlanInvariantPrepare.lean:28` redeclares
  `PlanData.afterPrepareGroup_remaining_subset`, already declared at
  `PlanInvariant.lean:899`. There is no fresh `.olean` for that module.
- **Scoped schedule-safety theorem: PASS.** The new `PlanInvariant.*` path
  genuinely derives readiness, exact actual `Step` projections, target
  `PlanData.Valid`, lifecycle `LWF/AC/ActiveExact`, and sequential version
  monotonicity from source invariants plus executable checks.
- **Broad “linear capability, transported but never copied” headline: FAIL.**
  A new kernel-checked counterexample accepted by the actual combined canonical
  plan checker turns one zero-demand remaining leaf into two remaining leaves
  and then mints two distinct prepared tickets. The present model proves
  demand-budget conservation, not discrete token/effect linearity.
- **Full exact authority-plan accounting: not established in this reviewed
  suite.** Main `PlanData.Valid` stores `B + E <= P`, not a leaf disposition
  ledger or `B + E + W = P`. `FullPlanInvariant.lean` was explicitly excluded
  from this review.

Accordingly, none of the current paper-facing results should be frozen as a
headline theorem until the duplicate declaration is fixed and the meaning of
“linear” is narrowed or strengthened.

## Frozen source

The exact SHA-256 list is in `frozen-hashes.txt`. The principal files were:

| File | SHA-256 |
|---|---|
| `PlanInvariant.lean` | `b0f6f2dc48de118604765a5e4d03cda4423e3f7b17e0ef4bc4bd7a75e1161f02` |
| `PlanInvariantPrepare.lean` | `e7f72976e00b7d09d72a92db3467a367002f16ef561a0670aa37e835997a374b` |
| `PlanInvariantTransport.lean` | `f8019a292b114a84e69efb0dd7a73fb42a00afd956514ee4c8b33dce37f83c9c` |
| `PlanInvariantDrop.lean` | `e288da9813c8a22c2447e2a3b0fcb8109f9c62544f39dc2e22ce4885b11b0f67` |
| `PlanInvariantMerge.lean` | `62aaecb14097912ee6824a94be6f38de5163993af650658acd2effb8d4f69477` |
| `PlanInvariantMergeExamples.lean` | `e5464e36c756598173bb9b0a4910ab38b4f6480509efb66ad932c2b222e00126` |
| `PlanInvariantGrammar.lean` | `5f9553bd596b847ad440e76a12876b58929b24ee661a4245a3ab906dee832c2f` |
| `PlanInvariantExamples.lean` | `e31a7be0ddd85274353196fb3cc040cbda73dca211145e10c521ef86d8042178` |

## Highest-severity semantic finding: zero-demand duplication

`ZeroDemandDuplication.lean` is an independent executable countermodel, not a
modification of project Lean source. It proves all of the following:

1. A source has exactly one `remaining` leaf, zero demand, a valid plan, and a
   valid canonical parallel-Fork operation.
2. The repository's combined `checkCanonicalPlan` returns `true`.
3. The transition is the actual `Step.canonical`, and the computed target plan
   is again `PlanData.Valid`.
4. `afterCanonical.remaining` contains two distinct child leaves.
5. Two successive valid `PreparePlanned` transitions mint two distinct
   prepared tickets, one for each child.

The final theorem is:

```text
ZeroDemandDuplication.two_distinct_tickets_from_one_source_leaf
```

It depends only on `propext`, `Classical.choice`, and `Quot.sound`.

The cause is structural. `Transfer.CoreValid.fiber_demand` requires only

```text
sum(child demand in a rho fiber) <= source demand
```

for each coordinate. A zero vector therefore places no bound on fiber
cardinality. `afterCanonical` puts every child in `childBatch` into
`remaining`; `Prepare` can then assign a distinct operation/ticket to each.
`zero_demand_child_visible` proves visibility, but neither it nor
`PlanData.Valid` proves uniqueness or conserved discrete authority mass.

Defensible wording is therefore **quantitative demand-budget transport** or
**root-preserving refinement**. “Linear capability,” “never copied,” and
“one-use authority identity” require an additional invariant, for example:

- every schedulable/authority-bearing leaf has a positive unit ghost
  coordinate;
- fiber conservation includes that coordinate; and
- zero-unit administrative fragments are excluded from `remaining/headGroup`
  and cannot mint tickets.

The stronger invariant and its target check must cover canonical transport and
both Merge modes. Merely recording zero-demand leaves is insufficient.

## Requested gate audit

| Audit question | Result | Finding |
|---|---|---|
| Hidden target `Valid`, readiness, root, batch, or load premises | **PASS, with an explicit-check caveat** | Paper-facing Prepare, restriction, Revoke, canonical, and Merge wrappers do not assume target `Valid`, target readiness, a caller-supplied target root/batch, or target load inequalities. Targets are computed. Canonical/Merge deliberately *do* require an executable Boolean scan of owner/root purity on the computed target. The generic `afterTransferCore_preserves_valid` also takes an authority equality and logical `CoreValid`; paper-facing wrappers derive these from definitions/checkers. Do not describe the path as “no target observation.” |
| Boolean CAS and actual `Step` projection | **PASS only for the sequential abstract relation** | `checkVersion = decide (offered = version)` is real executable equality, successful checks imply equality, mutating targets use `version + 1`, and every planned constructor projects to the repository's actual `Step`. It is not an atomic-store or concurrency proof: no interleaving, transaction, durability, failed CAS, or double-spend semantics is modeled. Two transitions may branch from the same mathematical source state. |
| Merge owner/root rejection | **PASS** | `crossSlotMerge_simulation_admitted_but_plan_rejected` proves actual simulation admission is `true` while the computed owner/root check is `false`. `AxiomAudit.lean` additionally proves this false conjunct forces the whole combined simulation-plan checker to return `false` for any plan carrying the witnessed root map. It does not construct a `Valid` `PlanData` instance for that particular older fixture, nor prove all cross-slot rejection/all same-slot acceptance. |
| Positive RTC coverage | **PASS for exactly the listed sublanguage** | `PositiveStep` includes Prepare; generic canonical `choiceFork`, `parallelFork`, `replaceRestore`, and `liveRestore`; restriction; Revoke; simulation/direct Merge; checkpoint; and all `TicketStep` variants. `positive_trace_preserves`, `projects`, and `version_mono` are genuine RTC inductions. Reserve is absent. This is a sequential checked sublanguage, not an operational model of cloned controller replicas or every raw `Step`. |
| Checkpoint/ticket stutter | **PASS** | Checkpoint is literal identity. Ticket dispatch/retry/crash/settle uses the real `TicketStep`; `ticketStep_auth_eq` justifies unchanged plan validity. This is sound because `PlanData.Valid` depends only on authority plus plan rows. It does not model workspace snapshot creation or external side-effect atomicity. |
| Version monotonicity | **PASS, scoped** | Every plan-mutating `PositiveStep` adds exactly one; checkpoint/ticket steps stutter; arbitrary positive traces are nondecreasing. There is no theorem tying a formal version check to an atomic database CAS, and raw underlying `Step` transitions remain available outside `PositiveStep`. |
| `LWF`, `AC`, `ActiveExact` | **PASS for `Safe` histories** | `Safe` contains all three lifecycle invariants plus plan validity. `PositiveStep.preserves_safe` applies the actual lifecycle preservation theorem to the actual projected step, then operation-specific plan preservation. `positive_trace_preserves` carries all four. The older Prepare-only `planned_prepare_trace_preserves` omits `ActiveExact`; use the unified theorem for the full statement. |
| Nonvacuity | **PASS for two Prepare edges** | `concrete_two_prepare_execution` is a closed two-slot, two-owner, two-operation witness with two actual `Step`s, version `+2`, strict remaining-cardinality decrease twice, and empty final remaining. Its conclusion states final `PlanData.Valid` but not final `ActiveExact`; the latter follows only through separate lifecycle preservation. The new zero-demand countermodel also establishes nonvacuity of the problematic path. |
| Claim discipline | **MIXED/FAIL for headline wording** | The scoped capacity and trace safety results are real. Exact leaf accounting, discrete linearity, concurrent CAS, enforcement completeness, progress/fairness, and physical exactly-once effects are not proved. |

## One-way enforcement boundary

`positive_trace_projects` proves:

```text
PositiveTrace  ->  AbstractTrace over Step
```

There is no converse theorem saying every runtime/`Step` mutation passed the
plan checker. The underlying `Step` relation still exposes unversioned
canonical, restriction, Revoke, and Merge constructors. Thus the formal result
specifies a safe checked sublanguage; an adapter/reference monitor must prove or
test that the real runtime cannot bypass it. Phrases such as “there is no
unversioned mutation path” are false for the repository as a whole.

## Exact accounting boundary

Main `PlanData.Valid` contains:

- exact durable exposure: `durableLoad = d0 + totalE`;
- live-load envelope: `L + E <= R`;
- deadline/cursor discipline; and
- selected-batch bound: `B + E <= P`.

It has no `W`, `LeafDisposition`, origin-token mass, or equation
`B + E + W = P`. The older `Plan.AuthorityPlan.ExactAccounting` does have an
algebraic `B + E + W = P`, but it is a separate single-`currentSlot` model and
its Prepare rule still takes `hbatchP` and `hPfits`. It also does not prevent
the checked zero-demand fiber duplication above. Results from these two models
must not be conjoined without an explicit integrated theorem.

## Precisely citeable theorems

The following are defensible with the stated scope after the build blocker is
removed:

- `PlanData.current_group_promotedLoad_le_capacity`: readiness derived from the
  source schedule invariant; no per-edge readiness premise.
- `PlanData.current_group_actual_step` and
  `PlanData.PreparePlanned.actual_step`: exact real Prepare projection.
- `PlanData.afterPrepareGroup_preserves_valid`: preservation of the eleven
  fields of current `PlanData.Valid`, not exact leaf accounting.
- `PlanData.plannedPrepareEdge_wellFounded`: well-foundedness of Prepare-only
  successful edges under remaining cardinality.
- `PlanData.planned_prepare_trace_preserves/projects/version_mono`: finite
  Prepare-only traces.
- `PlanData.checkCanonicalPlan_sound` and
  `PlanData.CanonicalTransportPlanned.preserves_all`: checked computed
  canonical transport, subject to the current non-linear refinement caveat.
- `PlanData.RestrictionPlanned.preserves_all` and
  `PlanData.RevokePlanned.preserves_all`: checked deletion operations.
- `PlanData.SimulationMergePlanned.preserves_all` and
  `PlanData.DirectMergePlanned.preserves_all`: checked Merge modes; direct mode
  explicitly uses target `checkAC`.
- `PlanData.PositiveStep.actual_step/preserves_safe/version_mono` and
  `PlanData.positive_trace_preserves/projects/version_mono`: the exact positive
  sequential sublanguage.
- `PlanData.crossSlotMerge_simulation_admitted_but_plan_rejected`: the concrete
  two-point negative Merge witness.
- `PlanInvariantExamples.concrete_two_prepare_execution`: closed two-Prepare
  execution witness.
- `PlanExamples.version_observation_lower_bound`: only a two-state
  indistinguishability result for the frozen `LocalAuthObs`; not a universal
  minimal-observation or semantic-cache completeness theorem.

## Not citeable as currently phrased

- Any theorem in `PlanInvariantPrepare.lean`: the module does not build at the
  frozen hash.
- `Plan.PreparePlanned.actual_step` or `PlanPreflight.PreparePlanned.actual_step`
  as evidence of readiness-free scheduling: both old relations explicitly
  assume `hbatchP` and `hPfits`.
- `Plan.planned_trace_preserves` as the unified multi-slot result: it belongs to
  the separate single-current-slot `AuthorityPlan` model.
- “The plan is a linear capability,” “transported but never copied,” “Fork
  cannot duplicate authority,” or “one source capability mints at most one
  ticket”: refuted by `ZeroDemandDuplication.lean`.
- “Exact `B+E+W=P` is preserved by the unified positive grammar”: not present in
  reviewed `PlanData.Valid`.
- “CAS is linearizable/atomic under concurrent agents”: the formal CAS is pure
  equality in a sequential transition.
- “All runtime histories are checked”: projection is one-way and Reserve/raw
  `Step` paths are outside the grammar.
- “Exactly once external effects”: tickets preserve stable bindings but do not
  prove physical effect atomicity or idempotence.
- “The semantic observation is globally sufficient/minimal”: only the tested
  safe/unsafe and irrelevant-mutation pairs are proved.

## Validation evidence

- `lake-build.log`: full build failure at the duplicate declaration.
- `fresh-leanchecker.log`: fresh kernel replay passes for every reviewed module
  except unavailable `PlanInvariantPrepare`.
- `prepare-stale-leanchecker.log`: confirms no `.olean` exists for the failed
  module.
- `axiom-audit.log`: exact signatures and axiom dependencies for the main
  paper-facing theorems; dependencies are only `propext`,
  `Classical.choice`, and `Quot.sound`.
- `placeholder-axiom-scan.log`: empty; no `sorry`, `admit`, project `axiom`, or
  `constant` in the scanned `Plan*.lean` source.
- `premise-scan.log`: audit trail for version/readiness/target-named premises.
- `zero-demand-duplication.log`: successful elaboration and axiom report for
  the adversarial two-ticket counterexample.

The build blocker is mechanical. The discrete-linearity counterexample is not;
it requires a theorem/model change or a narrower paper claim.
