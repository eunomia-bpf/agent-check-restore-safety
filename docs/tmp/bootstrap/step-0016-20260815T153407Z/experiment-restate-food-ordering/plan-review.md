# Plan Audit

No fresh reviewer was created for this experiment because the user fixed a one-reviewer limit earlier in the project. This file records the binding scientific and executability checks recovered from that existing review boundary plus the current read-only official-source audits. It is not represented as a new independent review.

## Decision

**Proceed conditionally.** The experiment is decisive only if the retained raw evidence establishes the exact H0/H1 comparison below. Infrastructure readiness, one successful order, or another lost-response recovery is dependency work and cannot be reported as the result.

## Binding Scientific Checks

1. H0 and H1 must use the same official application revision, order input, stable payment token derivation, target v2, and workflow cut.
2. Before replacement, the Restate journal and every Restate-visible workflow field used by version compatibility must be equal in H0 and H1. If they differ, the main comparison is invalid.
3. The payment closure must not have returned in either history. The only intended difference is the independently durable payment record: absent in H0 and present in H1.
4. The Requirement is fixed across H0 and H1 and still requires one payment and the remaining order result. Business Results and Capacities are also unchanged from v1. Target v2 has no executable payment producer. It retains one disabled historical kind only to interpret the old Operation; weakening the Requirement or leaving an executable charge path to make H0 pass is prohibited.
5. Target v2 is one ordinary new program used for both histories. It may accept the original order input, but it may not contain an old-version branch, a table of old states, an H0/H1 test, or per-instance migration code.
6. The proposed runtime must derive H1 `activate` and H0 `impossible` from History and the authoritative query. The no-query ablation must fail closed.
7. Native Restate and Temporal results are measured, not assumed. If Restate accepts both, H0 is an unsafe baseline acceptance. If it refuses both, it is safe but conservative. If its two answers differ because its journals differ, the decisive experiment is invalid. A manual version branch is reported separately.
8. Stable payment deduplication is not the claimed mechanism. The experiment provider is intentionally non-idempotent and a direct-retry control must create a second durable charge. Deliveries and durable commits are reported separately; H1 replacement must query the first committed fact without redispatching payment.
9. Old v1 code must be unable to issue a protected call after the v2 Rule becomes active. The run must retain evidence for the source invocation state, deployment removal, Rule activation point, and every protected delivery.
10. The independent checker must recompute the Rule decision and join it to effect truth and workflow completion. A runtime self-report is insufficient.

## Binding Executability Repairs Before Preflight

- Persist the exact registered HTTP request needed to query an unresolved Operation so recovery does not depend on the old caller resupplying bytes.
- Add an admin-only recovery path that uses the Operation contract already frozen in History; pure Rule compilation remains free of network side effects.
- Replace the official payment stub with a durable effect service supporting deterministic no-commit and commit-then-drop modes plus an authoritative query.
- Build immutable v1/v2 endpoints from the pinned official source and use official Restate registration and invocation commands.
- Retire or fence the source invocation before the new logical execution can issue protected calls. A crash between retirement and v2 start may delay completion but must not revive v1.
- Start v2 from its normal entry using the original order input. Any target-specific conversion of Restate journal state is a kill condition, not acceptable glue.

## Kill Criteria

The headline result is invalid if any of the following occurs:

- H0 and H1 have different Restate journals at the claimed cut;
- H0 reaches the terminal order state without a durable payment;
- H1 needs v1, a manual state branch, or copied internal Restate state;
- payment is delivered again after the runtime has accepted the authoritative H1 fact;
- the provider deduplicates repeated POSTs by token or Operation ID;
- v1 issues a protected call after v2 activation;
- the observer, runtime, and independent effect record disagree;
- the same evidence yields different compiler and checker decisions;
- a compatible edit fails in either proposed or baseline path because of avoidable configuration differences; or
- native Restate or Temporal automatically makes the same H0/H1 distinction with the same available facts and no developer-written migration.

## Scope If Successful

Success supports automatic replacement for this registered, queryable HTTP effect and this maintained workflow. It does not establish arbitrary exactly-once execution, dishonest-provider recovery, all Restate applications, or a production atomic cut across an unmodified workflow engine.

The current JSON places business Results/Capacities and the target program's operation catalog inside one Requirement. Consequently its hash changes when v2 removes an executable kind even though the business obligation is unchanged. The experiment must report this representation boundary explicitly; it must not claim that the entire v1 Requirement object is byte-identical to v2.
