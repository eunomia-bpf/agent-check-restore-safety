import AuthorityContinuity.Trace

/-!
# Authority Continuity

This is the replay root for the finite RQ3 mechanization.  Importing it
elaborates the executable checker, exact restriction and Prepare construction,
closed lifecycle kernel, temporal non-resurrection results, labeled concrete
simulation, effect coverage, and the conditional trace theorem.

The separate `AuthorityContinuity.Audit` module prints the kernel dependencies
of every paper-facing theorem.  Boundary I/II and concrete product-runtime
refinement are deliberately outside this root's mechanized scope.
-/
