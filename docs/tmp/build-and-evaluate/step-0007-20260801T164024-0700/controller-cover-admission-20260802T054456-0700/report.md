# Controller-cover admission theorem and executable alignment

Date: 2026-08-02

## Question

Can the history-admission tool use a small, theorem-guided controller model
that is more general than a one-controller-per-cell partition, while honestly
separating semantic safety from runtime realization?

## Outcome

Yes.  The implementation and Lean model now share the following spine:

```text
typed Fork/Restore/Merge
  -> Candidate, Required
fixed durable prefix
  -> Admitted
declared co-live controller product
  -> RawPhysical
runtime refinement obligation
  -> Required <= Actual <= RawPhysical <= Admitted
```

The executable compiler and independent verifier classify a deterministic bad
cover as `OutsideSupport`, `LocalOverpermission`, or `CorrelationCut`.
`GateClone` and `GateCut` are emitted only for the last class.  The compiler's
seal remains structural and always sets `effect_authorizes` to false.

The new Lean module
`AuthorityContinuity/ControllerCoverAdmission.lean` mechanizes arbitrary
overlapping cell/controller access, local controller families, co-liveness,
raw and support-restricted products, deployment readiness, the exact
obstruction criterion, runtime-family certificate transport, a conditional
bridge to the older functional partition theorem, a canonical construction
that discharges that bridge for functional partitions, and a U(2,3)
higher-order GateCut fixture.

## Soundness corrections made during hostile review

1. A physical configuration containing a cell outside admitted support is no
   longer mislabeled as a minimal nonface.
2. A locally forbidden controller choice is no longer called a distributed
   GateCut.
3. Deployment readiness uses the raw controller product; support restriction
   is used only to extract admitted minimal nonfaces.
4. `GateCutWitness` requires every selected local piece to be admitted.
5. Readiness failures are an inclusive disjunction: overpermission and missing
   required behavior may occur together.
6. The full runtime relation is stated as an external refinement obligation;
   `Required <= RawPhysical` alone does not imply `Required <= Actual`.
7. No canonical functional equality is claimed for arbitrary overlapping
   covers.  For the actual functional-partition case, the development now
   constructs the access relation, local families, co-live family, and cover
   plan and proves that their raw physical product equals the older local
   product.  Thus the earlier partition theorem is a derived special case,
   rather than a premise supplied by the adapter.
8. The Lean fixture is called GateCut, not GateClone, because controller-origin
   provenance is not represented in that module.

## Validation

- Python artifact: 55 unit tests pass, including all six typed operators, all
  deployment grades, the three failure classes, tamper checks, and the
  exhaustive 2,166-case three-cell refinement oracle.
- Direct Lean elaboration of `ControllerCoverAdmission.lean`: pass with no
  warning.
- `lake build AuthorityContinuity.Main`: pass.
- New paper-facing theorem dependencies: only `propext`, `Classical.choice`,
  and `Quot.sound`; no `sorry`, `admit`, or project axiom.
- Independent hostile semantic audit: no kernel or semantic soundness blocker;
  one inaccurate exclusivity comment was corrected.
- Full source/frozen-theorem/fresh-kernel audit: pass.  The audit confirmed all
  frozen theorems and controls and completed a fresh `leanchecker` replay.

## Claim boundary

The finite product and minimal-nonface machinery are classical supporting
mathematics.  The defensible contribution is their typed, proof-producing
composition at a history-transformation boundary: normalize redemption cells,
derive operator-specific future families, condition them on the immutable
durable past, independently normalize controller realization, check the
manifest sandwich, and emit independently replayable positive or negative
evidence.

The theorem does not establish truthful manifests, complete mediation,
controller freshness, atomic external redemption, natural-language intent,
lease validity, external exactly-once execution, or the two runtime relations
involving `Actual`.
