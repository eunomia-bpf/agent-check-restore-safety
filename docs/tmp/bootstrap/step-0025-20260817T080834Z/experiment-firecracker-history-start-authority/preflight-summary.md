# Step 0025 preflight summary

Final disposition: **real-system experiment not admitted**.

The frozen plan allowed at most three complete real preflight attempts. All
three failed before producing a complete H1/H0/control triple:

1. Attempt 1 failed closed before `InstanceStart` because typed runtime facts
   were not encoded as canonical JSON.
2. Attempt 2 reached the first guarded VM and official Claude but did not
   retain enough relay evidence to distinguish application readiness from the
   final effect path.
3. Attempt 3 observed a successful, separately identifiable readiness request
   immediately before measurement and localized the measured failure to a
   missing gateway-to-provider request-hash header. The executed adapter path
   rejected before upstream I/O and the Operation became `unknown`.

Every attempt retained available run-level evidence and recorded zero measured
effect-adapter deliveries; attempt 2 did not retain its cell-local evidence,
and none of the failed attempts retained a terminal Mongo observation from
which to make a broader no-commit claim. Every residual-process check was
empty. Corrections for all three causes have regression tests, but the final
correction has no subsequent real-system run. The preflight was therefore not
sealed, the three-repetition matrix was not started, and no positive systems
or paper claim follows from Step 0025.
