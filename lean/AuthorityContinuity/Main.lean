import AuthorityContinuity.Audit
import AuthorityContinuity.PlanTokenStrengthening
import AuthorityContinuity.TokenWeightedAccounting

/-!
# Authority Continuity

This is the replay root for the finite RQ3 mechanization.  Importing it
elaborates the executable checker, exact restriction and Prepare construction,
computed canonical Fork/Restore targets, checked simulation/direct Merge,
the single closed lifecycle relation, separating witnesses, temporal
non-resurrection results, labeled concrete simulation, effect coverage, and
the conditional trace theorem.  It also replays source-derived token
non-amplification, durable operation-token continuity, and epoch-qualified
identity/weighted accounting for the token-aware plan grammar.

`AuthorityContinuity.Audit` prints the kernel dependencies of every
paper-facing theorem.  Boundary I/II and concrete product-runtime refinement
are deliberately outside this root's mechanized scope.
-/
