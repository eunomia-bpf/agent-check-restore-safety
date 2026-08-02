# Controller-observation arity lower bound

## Question

Can a history-admission checker replace the controller co-liveness relation
with a pairwise controller graph while retaining an exact deployment decision?

## Result

No, in the worst case.  The mechanized fixture fixes all of the following
between two realizations:

- `Required = Admitted = U(2,3)`;
- three redemption cells and three controller identities;
- the complete cell-to-controller access relation;
- every controller-local family; and
- the complete co-liveness projection through arity two.

The first realization permits exactly the controller sets of cardinality at
most two.  Its raw physical product is exactly `U(2,3)`, so it is deployment
ready.  The second permits every controller set.  It realizes the forbidden
three-cell configuration using three locally admitted singleton choices and is
not deployment ready.  Both co-liveness families are downward closed.

The generic observation-collision lemma then proves that no checker restricted
to the common pairwise observation can be both sound and complete for all
controller realizations.  A fail-closed checker remains possible, but it must
reject at least one safe realization if it omits the higher-order evidence.

## What this contributes

The underlying boundary-versus-filled-simplex fact is classical.  The paper's
claim is narrower: it becomes an input lower bound for history admission.  It
explains why the compiler manifest cannot, in general, replace the full
co-liveness family with a pairwise conflict graph.  The result is worst-case;
pairwise evidence can suffice under an additional flag-complex or other
pairwise-to-global adapter obligation.

## Mechanized declarations

- `coLiveProjection`
- `no_exact_checker_of_observation_collision`
- `pairwise_raw_eq_rankTwo`
- `pairwise_realization_ready`
- `triple_realization_correlationCutWitness`
- `triple_realization_not_ready`
- `pairwise_projection_collision`
- `no_pairwise_observation_checker_exact`

## Checks

- `lake build AuthorityContinuity.ControllerCoverAdmission`: pass.
- `lake env lean AuthorityContinuity/Audit.lean`: the new paper-facing
  declarations depend only on the repository's existing whitelist of
  `propext`, `Classical.choice`, and `Quot.sound`; no `native_decide` axiom is
  present.
- The repository-wide `leanchecker --fresh AuthorityContinuity.Main` replay
  remained CPU-bound after 15 minutes and was stopped.  This is recorded as a
  resource-incomplete diagnostic, not as a passing or failing proof result;
  module elaboration and the per-declaration axiom audit above did complete.
