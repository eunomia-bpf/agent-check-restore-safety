# Rejected main-run pilot

**Verdict:** REVISE; this run is not paper evidence.

The first 80-run execution completed without runtime failures and the initial
checker passed, but an independent result attack found three blockers in the
evidence construction:

1. The C16/C18 observation action used a fabricated common grant name instead
   of the actual next-action grants.  That erased the action-to-prefix alias
   relation rather than merely alpha-renaming it.
2. C02/C04 labeled the same physical-attempt question from the oracle, but C04
   did not execute an admission decision after settlement.  Its cached return
   was correct, yet the claimed observation pair remained counterfactual.
3. C19 called its Merge `certified` but supplied no canonical projection or
   claim-transfer map for the controller and independent replay decoder to
   validate.

The revision does not change any oracle decision.  Litmus suite revision 2:

- uses each actual C16/C18 grant ID and represents grants, delegations, and
  claims with explicit typed IDs so O2 preserves aliasing while O0/O1 do not;
- executes an explicit attempt-admission probe while the real callback remains
  pending: C02's recovery Dispatch accepts and physically attempts once, while
  C04's Retry rejects as a durable stutter before returning the cached receipt;
- adds a canonical C19 target/source projection and injective retained-claim
  map, validated independently by controller and replay implementations; and
- checks modeled provider topology, tool dispatch, worker fault boundary, sink
  outcome, and controller edges against raw App Server JSONL and durable state.

The rejected pilot artifacts are retained under `pilot-rejected/`.  Only a
fresh suite-revision-2 run may populate `adapter/results/` and be considered by
the final result review.
