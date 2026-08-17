# Checked Merge and unified positive grammar report

## Verdict

**PASS.**  Simulation-certified Merge, direct-AC Merge, and the requested
mixed-operation positive trace theorem were all obtained without target
validity, readiness, root-map, batch-map, or load-bound premises.

Sources:

- `lean/AuthorityContinuity/PlanInvariantMerge.lean`, SHA-256
  `62aaecb14097912ee6824a94be6f38de5163993af650658acd2effb8d4f69477`;
- `lean/AuthorityContinuity/PlanInvariantMergeExamples.lean`, SHA-256
  `e5464e36c756598173bb9b0a4910ab38b4f6480509efb66ad932c2b222e00126`;
- `lean/AuthorityContinuity/PlanInvariantGrammar.lean`, SHA-256
  `5f9553bd596b847ad440e76a12876b58929b24ee661a4245a3ab906dee832c2f`.

The generic dependency was the frozen
`PlanInvariantTransport.lean` at SHA-256
`f8019a292b114a84e69efb0dd7a73fb42a00afd956514ee4c8b33dce37f83c9c`.

## Computed Merge target

For an actual `MergeDescriptor d`, `afterMerge p d` is definitionally
`afterCanonical p d.transfer`:

- `version := p.version + 1`;
- `rootSlot := transportedRoot p.rootSlot d.transfer`;
- `remaining := childBatch d.transfer p.remaining`;
- schedule rows `slots/d0/cap0/R/P/E` remain unchanged because `targetCore`
  preserves capacity, demand, and durable load.

The actual lifecycle target is exactly `d.target A`, whose authority is
definitionally `d.transfer.targetCore A d.allowed`.

## Simulation Merge gate

`SimulationMergePlanned` admits only:

- source LWF, AC, ActiveExact, and `PlanData.Valid`;
- executable durable version CAS;
- the repository's real `MergeCheck.simulationAdmission`; and
- executable `checkTargetOwnerRootPure` over `d.target`'s computed authority
  and the transported source root map.

`simulationAdmission` contains the structural checker, whose soundness yields
the exact `Transfer.CoreValid` needed by the frozen generic theorem.  That
theorem derives target `L`, `B`, durable equality, reservation envelope, batch
bound, cursor phase, structural plan fields, and therefore complete target
`Valid`.

The relation proves:

- version CAS soundness and exact successor;
- target plan validity;
- actual `Step.simulationMerge`; and
- target LWF, AC, and ActiveExact through the simulation proof path.

`checkSimulationMergePlan` combines the three executable admission atoms, and
`simulationMergePlanned_of_check` reconstructs the relation from its result.

## Direct Merge gate

The direct wrapper is also sound and did not require narrowing.  Its
`directAdmission` contains the same structural checker, so plan preservation
uses the same `CoreValid` theorem and computed owner/root check.  It remains a
separate `DirectMergePlanned` relation because lifecycle AC is obtained from
the explicit target `checkAC`, not from a configuration simulation.

No claim equates the security or operational cost of the two modes.

## Cross-slot negative witness

The concrete witness is isolated in `PlanInvariantMergeExamples.lean`; the
generic Merge and grammar modules therefore do not depend on the example
suite.

The existing fixture establishes both:

```text
MergeCheck.simulationAdmission source crossSlotMerge crossSlotProject = true
checkTargetOwnerRootPure source crossSlotMerge.transfer
  crossSlotMerge.allowed sourceRootSlot = false
```

The rejection has a concrete witness: target owner `x` co-owns claims `a` and
`c`, whose transported roots remain distinct slots `a` and `c`.

This result says that lifecycle simulation alone is insufficient for plan
continuity.  It does **not** say all cross-slot Merges reject, nor that all
same-slot Merges accept.  A same-slot descriptor is admitted only if every
actual executable check succeeds; no universal same-slot acceptance theorem
was asserted.

## Unified positive grammar

`PlanInvariantGrammar.lean` adds the requested
`CanonicalTransportPlanned` wrapper and one `PositiveStep` grammar over:

- checked group Prepare;
- checked canonical Fork/Restore transport;
- checked restriction;
- checked Revoke;
- checked simulation Merge;
- the separately checked direct Merge mode;
- checkpoint plan stutter; and
- actual ticket dispatch/retry/crash/settle lifecycle steps with plan stutter.

`Safe S` couples lifecycle LWF, AC, ActiveExact, and full plan `Valid`.
For arbitrary `Relation.ReflTransGen PositiveEdge` histories, the module
proves:

1. `positive_trace_preserves`: target `Safe`;
2. `positive_trace_projects`: erasure is an actual repository
   `AbstractTrace`; and
3. `positive_trace_version_mono`: durable plan version never decreases.

Every plan-mutating edge advances the version exactly once.  Checkpoint and
ticket/recovery edges preserve the plan and version.  Ticket validity
preservation uses the actual theorem that ticket steps leave the authority
projection unchanged.

## Claim boundary

- This is a **positive admitted grammar**, not a claim that every raw runtime
  mutation can be transported.
- Reserve is not part of this small grammar; admitting a fresh tentative claim
  requires a separate computed plan-allocation policy.
- The RTC theorem proves invariant preservation, lifecycle projection, and
  version monotonicity.  It does not prove fairness, progress, scheduling
  termination, or that an application-level Merge is desirable.
- Version monotonicity is intentionally non-strict because checkpoint and
  ticket/recovery edges stutter the plan.
- Owner/root purity is an additional plan-continuity check; it is not implied
  by lifecycle AC or Merge simulation.

## Validation

- pinned Lean 4.30.0 builds: pass;
- fresh `leanchecker --fresh` for grammar and Merge-examples dependency
  closures: pass;
- forbidden proof scan: clean;
- target/readiness-oracle scan: clean;
- axiom audit: only `propext`, `Classical.choice`, and `Quot.sound`.
