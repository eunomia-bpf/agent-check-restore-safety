# Independent Plan Review

## Round 1

Verdict: **revision required before execution**.

The reviewer judged the experiment high-value and nonredundant, but identified
five blocking causal and enforcement gaps:

1. H0 did not exercise the same unknown Operation state as H1.
2. QEMU resume ordering was observed but not exclusively enforced.
3. The plan incorrectly described endpoint attachment and resume as part of the
   atomic Rule/binding cutover.
4. The common checkpoint lacked a complete sealing and per-lane verification
   protocol.
5. The retained-evidence oracles and authoritative commands were underspecified.

Accepted repairs:

- H0 and H1 now use the same sealed checkpoint, byte-identical target,
  alpha-equivalent request and Operation identity, and normalized
  `prepared -> dispatched -> unknown` History. H1 differs only because Mongo
  contains the committed result; H0 has a durable terminal pre-upstream fence
  plus an exact zero-row query, so the request cannot commit later.
- QMP is owned only by an exclusive guard. A one-use resume authorization binds
  the checked Certificate and History head, target hash, sealed checkpoint and
  machine configuration, QEMU process identity, replacement binding, and
  endpoint publication. H0 must attempt the same resume and be denied.
- Only Rule plus sandbox-binding cutover is atomic. Endpoint readiness and the
  guarded `cont` follow in fail-closed order.
- The base QEMU process closes before the full qcow2 and canonical machine
  configuration are sealed. Every lane copy is verified before QEMU opens it,
  starts paused, and loads the named snapshot.
- The plan now fixes commands and raw oracles for Mongo documents, terminal
  fences, barrier acknowledgments, QMP commands/replies, endpoint readiness,
  stale generations, process reaping, Agent completion, and no redispatch.

The revised plan is resubmitted to the same reviewer solely to verify these
blockers before implementation.

## Round 2

Verdict: **approved**.

The same reviewer confirmed that all five blockers are resolved sufficiently
to begin implementation. The implementation must preserve the exact order in
the plan's "Enforced activation order" paragraph; the shorter preflight
summary does not override that protocol.

## Post-preflight amendment review

Verdict: **implementation correction approved; direct full run prohibited**.

The reviewer confirmed that the safety invariant is that guest vCPUs have not
run and only the guard can issue `cont`, not QEMU's literal `paused` label.
For an initial `-S -loadvm before_agent` state, the exact required observation
is `status=prelaunch,running=false`; after an explicit `stop`, it remains
`status=paused,running=false`. Renaming the initial evidence event to
`snapshot-loaded-halted` preserves and clarifies the causal boundary.

However, all three admitted preflights failed before any Agent/application
request, so none met the plan's end-to-end preflight rule. The reviewer ruled
that a direct full run would bypass rather than satisfy the three-attempt cap.
Step 0023 must stop incomplete and return to orchestration. Any later execution
must be separately admitted and must disclose this inheritance.
