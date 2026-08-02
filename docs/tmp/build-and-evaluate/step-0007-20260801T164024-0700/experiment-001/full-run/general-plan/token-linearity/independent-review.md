# Independent semantic review: token linearity and full-plan accounting

Date: 2026-08-01 (America/Vancouver)

## Verdict

**REVISE for a paper-facing integrated claim; ACCEPT the token module as a
sound fixed-plan-epoch, target-revalidating reference monitor.**

The new token layer closes the concrete zero-demand duplication admission hole
in its stated checked grammar.  The executable checker covers actual current
plan members and actual durable `opClaim` bindings, the local regression
reproduces the essential frozen counterexample, and arbitrary
`TokenPositiveTrace` histories preserve `TokenSafe` and project to the existing
actual lifecycle semantics.

The suite is not yet one end-to-end theorem combining discrete token
linearity, `B + E + W = P`, dynamic agent plan creation, and all checked
operations.  `PlanTokenLinearity.lean` and `FullPlanInvariant.lean` are
disconnected modules.  Moreover, most mutating token "preservation" theorems
obtain the target invariant by running `checkLinear` over the complete target;
their source-linearity hypotheses are unused.  That is a legitimate verified
reference-monitor design, but it is not derivational conservation and should
not be presented as such.

## What is genuinely established

### Discrete state and executable admission

`LinearValid` is a meaningful discrete invariant.  It covers every selected
current claim and every actual operation whose `opClaim` is defined, bounds
both token fibers by one, prohibits a simultaneous current and durable witness,
and makes the stored disposition agree with the state-derived disposition.
`checkLinear_sound` turns the finite Boolean scan into that proposition.

`LinearValid.token_trichotomy` then proves, for each token in `initial`, exactly
one of these cardinality cases:

1. `remaining`: one current witness and no operation binding;
2. `prepared`: no current witness and one operation binding; or
3. `withdrawn`: neither witness.

This result does not use demand positivity, so a zero-vector claim remains a
discrete object.  Note that `prepared` means "has an `opClaim` binding" across
all ticket/receipt phases.  It is not a distinct proof of prepared versus
dispatched, settled, or physically effected state.

### Zero-demand regression

The closed fixture has the same essential source, transfer, `parallelFork`, and
zero-valued plan as the frozen `ZeroDemandDuplication.lean` witness, with one
additional initial token.  Kernel evaluation proves that:

- the source token scan succeeds;
- the old canonical plan checker succeeds;
- the combined canonical checker fails; and
- the unchecked target contains two current claims in the same token fiber.

Therefore the old two-child fork cannot cross the new canonical admission
gate.  This is the central successful result.  A useful future tightening is
an explicit theorem that the safe old source has no corresponding
`TokenPositiveStep`, rather than only the current Boolean rejection theorem.

### Actual lifecycle bindings and the global-`rho` attack

I attacked `TokenLedger.transportedOrigin` because it applies `rho` to every
claim ID.  If a claim already named by a durable ticket or receipt could lie in
the transfer domain, Canonical or Merge could silently change the token of an
existing operation while a target scan still passed.

That attack is ruled out under the actual source safety premises:

```text
opClaim e = some c
  -> LWF.bound_durable gives status(c) = durable
  -> Transfer.rho_eq_none_of_durable gives rho(c) = none
  -> transportedOrigin ledger tr c = ledger.origin c
```

Canonical and Merge also preserve `opClaim` definitionally.  The independent
kernel audit proves `bound_durable_origin_survives_afterTransfer` from exactly
these premises.  Thus a valid checked Canonical/Merge step cannot use `rho` to
rebind an existing ticket/receipt claim to another token.

This important argument is currently implicit across modules.  It should be
exported as a paper-facing per-step theorem and lifted to the RTC theorem.  The
claim is conditional on source `LWF` and valid transfer provenance; the bare
target Boolean alone does not establish it.

### Honest operation coverage

The current coverage is sound with the following exact reading:

| Operation | Established meaning |
|---|---|
| Canonical Fork/Restore | Choice fork, parallel fork, replacement restore, and live restore use the existing computed canonical target and a complete target token scan. This is topology-level semantics, not arbitrary process checkpoint/restore. |
| Merge | Simulation and direct Merge use their actual computed targets and complete target token scans. |
| Prepare | The existing current-head `advancePrepare` and actual assignment/cleanup are used; a checked head token obtains an actual `opClaim` witness, and same-token operation duplication is rejected. |
| Restriction/Revoke | The actual computed targets are scanned; withdrawal is derived from absence of both target witness kinds. |
| Ticket phases | Dispatch/retry/crash/settle preserve token linearity source-to-target because the existing `TicketStep` keeps `opClaim` stable, including transfer to a receipt. |
| Checkpoint | Literal identity only. It does not model snapshot creation, resource closure, or restore admission. |
| RTC | Arbitrary sequential histories in `TokenPositiveStep` preserve `TokenSafe`, keep `initial` fixed, and project one-way to the existing `Step` trace. |

`Reserve` is absent.  The trace theorem is for a sequential checked sublanguage,
not a converse saying that every raw runtime `Step` passed the monitor.  Version
equality is not a proof of a durable linearizable CAS under concurrent agents,
and logical ticket uniqueness is not exactly-once behavior in an external
service.

## Successful attack: target revalidation is not derivational preservation

The mutating checkers are old operation admission conjoined with
`checkLinear(computedTarget)`.  Consequently
`checkedCanonical_preserves_linearity`, both Merge variants, Prepare,
Restriction, and Revoke can derive their target result from the target scan
alone.  Their source `LinearValid` argument is unused.

The review-only Lean audit gives a concrete witness:

1. take the unchecked zero-demand fork target, whose one token has two current
   witnesses and therefore is not `LinearValid`;
2. Restrict the target to one of those claims; and
3. observe that `checkRestrictionTokenPlan ... = true` and the repaired target
   passes `checkLinear`.

The kernel proves both `invalid_source_not_linear` and
`target_only_restriction_accepts`.  Thus the checker can accept an edge from an
invalid token source to a valid target.  This does not refute
`token_positive_trace_preserves`, because that theorem assumes `TokenSafe` at
the trace source.  It does fix the correct contribution:

> Within a fixed admitted plan epoch, a computed transition is allowed only if
> the existing operation checker and a sound complete target-state token scan
> both succeed; arbitrary histories starting in `TokenSafe` remain safe.

Do not call this source-derived token conservation or claim that source
linearity is what proves each mutating target linear.  The current proof is
close to reference-monitor soundness by construction.

### Existing nontrivial ingredients

The work is not wholly tautological.  The nontrivial parts currently come from:

- deterministic computed targets rather than caller-proposed targets;
- the existing checked plan/lifecycle grammar and projection to actual `Step`;
- transfer provenance and the prohibition on putting durable IDs in `rho`;
- stable `opClaim` across canonical, Merge, restriction, revoke, and ticket
  phases;
- actual Prepare assignment/cleanup semantics;
- the exact token-fiber trichotomy; and
- RTC composition, version monotonicity, and within-epoch non-minting.

Ticket and checkpoint preservation are genuinely source-derived.  The durable
origin lemma is also derivable from source invariants, as the independent audit
demonstrates, but is not exported by the token module.

### Minimum strengthening for a principle-level contribution

Keep the complete target scan as defense in depth, but add local, explanatory
admission atoms and source-derived theorems:

1. For Canonical/Merge, define a checked **token non-amplification** property
   over the actual `rho` fibers: one source token may induce at most one target
   current witness.  Prove it equivalent to target current-fiber linearity
   under source coverage and the computed child-batch theorem.
2. Prove durable operation-token binding stability for Canonical/Merge,
   Restriction/Revoke, Prepare, and ticket phases, then lift it through RTC.
3. Derive Restriction/Revoke linearity from fiber-subset and stable-binding
   lemmas; these operations should not need a whole-target scan for the proof.
4. Derive as much Prepare preservation as possible from assignment
   injectivity, source exclusivity, actual head removal, and stable prior
   bindings.  Leave a small explicit admission condition for the part that is
   not derivable.
5. State a characterization theorem showing exactly which Canonical/Merge
   `rho` patterns the local token atom rejects.  This makes the mechanism
   useful to runtime implementers rather than merely rechecking a global
   invariant.

## Fixed `initial` and dynamic agent plans

`token_positive_trace_initial_eq` proves that no edge in the present grammar
mints a token.  This is useful and honest only **within one admitted plan
epoch**.  It is too narrow as a lifetime model for Claude/Codex-like agents,
which create subgoals, spawn children, replan after observations, and discover
new tool calls online.

The theorem fixes only the `initial` set.  The claim-to-token `origin` map is
intentionally rewritten along `rho`; it is not globally equal across a trace.
What is defensible is active-lineage transport plus durable-binding stability,
not global immutability of every inactive claim-ID entry.

The current model has no trusted initializer theorem, plan-epoch identifier,
dynamic extension transition, mint authorization, or cross-epoch freshness
ledger.  `initial` is supplied by the caller at state construction.  Therefore
the paper should say:

> Tokens are fixed for the duration of one admitted plan epoch.  Plan creation
> and online extension are outside the current theorem and must mint fresh
> tokens at an explicit authority-checked epoch boundary.

A useful industrial extension is `PlanEpochStart` or `ExtendPlan`, guarded by
a controller-version CAS and carrying:

- an epoch-qualified token identity and monotone `everIssued` set;
- freshness/disjointness from every prior token, not merely the current plan;
- an authority/capability budget that justifies each new token;
- a mapping from each minted token to the admitted plan node, resource set,
  and root slot;
- reconciliation or preservation of all prior durable/uncertain operations;
  and
- a rule that Fork/Restore never implicitly mints or resurrects old tokens.

Without this boundary, "splitting requires pre-minting before plan creation"
is a sound static-plan statement but not yet an algorithm for dynamically
generated agent workloads.

## `B + E + W = P` is separate, not integrated

`FullPlanInvariant.lean` proves a valid but narrower arithmetic result for
computed Prepare.  `AuthorityPlan.ExactAccounting` is exactly

```text
forall slot coordinate, B + E + W = P.
```

Here `B` is computed from the remaining claim batch, while `E`, `W`, and `P`
are stored vector rows constrained by the equation.  The Prepare theorem
computes the target `W` as an arithmetic residual and proves the equation by
the source equation and schedule bounds.

It does **not** currently prove that:

- `E` equals a sum over actual prepared tickets/receipts;
- `W` equals a sum over claims or tokens classified `withdrawn`;
- `P` is the sum of immutable per-token budgets;
- the claim-level `LeafDisposition` agrees with `TokenDisposition`; or
- token origin/root transport agrees with the full plan ledger.

There is no import in either direction between `FullPlanInvariant` and
`PlanTokenLinearity`, no combined state, no coherence predicate relating their
dispositions, and no theorem containing both `ExactAccounting` and
`LinearValid`.  `FullPlanInvariant` itself covers only Prepare, not Canonical,
Merge, Restriction, Revoke, tickets, checkpoint, or RTC.  Therefore the exact
equation and token trichotomy must be presented as two complementary but
currently separate results.

Also, `afterPrepare_preserves_full` by itself preserves only schedule validity,
representation coherence, and the equation; it does not conclude lifecycle
`LWF`, `AC`, or `ActiveExact`.  `checkedPrepare_preserves_full` separately
supplies the real Prepare relation and `Step` under the executable assignment
premises, but there is still no single `FullSafe` record carried by an RTC.

The clean unification is a token-weighted accounting model.  Give every issued
token an immutable epoch, root slot, and vector budget, and define `B`, `E`,
and `W` as sums over the three token dispositions.  Token trichotomy would then
derive `B + E + W = P`, including the zero-vector case without losing the
token's cardinality.  A combined grammar-preservation theorem would be a
substantially stronger, less ad hoc contribution than merely pairing the two
present records.

## Using the paper-formation agent trajectory

The paper-formation Codex lineage is an appropriate **real longitudinal
workload and schema-gap case study**, not proof of safety.  The existing
private audit observes dynamic delegation/fork structure, goal updates,
compactions, a UI rollback marker, repeated workspace mutation, tool
call/result correlation, and outward-looking wrapper shapes.  Those are the
right workload pressures for plan epochs, fork provenance, restore admission,
and durable effect tickets.

The trace lacks the fields needed to decide the formal predicate: plan
epoch/version, token mint and origin, capability/grant lineage, snapshot
manifest, stable protected-operation ID, effect phase, durable receipt, and
external reconciliation.  A UI rollback is not semantic Restore; a call ID is
not a durable effect ticket; and a completed wrapper is not a remote receipt.

Use the private lineage to:

1. motivate why workspace rollback is incomplete and why plans are dynamic;
2. derive the minimum runtime telemetry contract;
3. replay the observed action *shapes* through an instrumented Claude/Codex
   adapter; and
4. seed synthetic/fault-injection tests for fork, stale epoch, crash-after-
   dispatch, duplicate retry, restore, restriction, and reconciliation.

Do not infer an unsafe-restore rate or claim the current formal algorithm was
validated by the old trace.  The separate method review also marks the current
private extractor **REVISE** because its child-native boundary heuristic and
double-blind/privacy scrub need strengthening.  Until fixed, report its exact
counts as provisional internal evidence.  Public TraceLab-like data can supply
breadth, while the private paper trace supplies longitudinal mechanism shape
and controlled instrumented experiments supply causal safety evidence.

## Reproduction and kernel evidence

Frozen source hashes are in `independent-frozen-hashes.txt`.  The duplicate
`afterPrepareGroup_remaining_subset` declaration has been removed: the only
remaining declaration is in `PlanInvariant.lean`.

- `lake build AuthorityContinuity`: **PASS**, 8,502 jobs.
- Review-only `IndependentAudit.lean`: **PASS**.  It proves the durable-origin
  defense and the target-only repair counterexample.
- Scoped static scan for `sorry`, `admit`, source `axiom`/`constant`,
  `native_decide`, `unsafe`, and `partial`: **PASS**, no matches.
- Printed dependencies for reviewed theorems and review obligations contain
  only Lean/Mathlib's accepted `propext`, `Classical.choice`, and `Quot.sound`
  (the durable-origin lemmas do not require `Classical.choice`).
- Fresh `leanchecker` for `AuthorityContinuity.PlanTokenLinearity`:
  **PASS**, exit 0 in 867.44 seconds.
- Fresh `leanchecker` for `AuthorityContinuity.FullPlanInvariant`:
  **PASS**, exit 0 in 871.57 seconds.

One validation integration issue matters: `AuthorityContinuity.Main` imports
`AuthorityContinuity.Audit`, and that root currently imports neither new
module.  A fresh replay of `Main` therefore does not replay these additions,
although the library glob makes the full Lake build compile them.  Add the new
paper-facing modules/theorems to the audit root before claiming that the root
fresh replay covers the complete formal suite.

Raw evidence retained beside this report:

- `IndependentAudit.lean` and `independent-audit-lean.log`;
- `independent-lake-build.log`;
- `independent-fresh-token-leanchecker.log`;
- `independent-fresh-fullplan-leanchecker.log`;
- `independent-static-scan.log`; and
- `independent-frozen-hashes.txt`.

## Acceptance gate

For the narrow token-reference-monitor result, the implementation is already
acceptable if the module-specific fresh replays pass and the wording remains
within the limits above.

For the larger paper claim, change this review to **ACCEPT** after:

1. the token trichotomy and exact vector equation are connected by a semantic
   combined invariant, or explicitly demoted to separate contributions;
2. target revalidation is named honestly and augmented with local
   source-derived/non-amplification theorems;
3. durable operation-token stability is exported and lifted through RTC;
4. the plan-epoch/mint boundary is modeled or clearly excluded;
5. the audit root imports and fresh-replays both new modules; and
6. trajectory evidence is used as a workload/schema-gap case plus controlled
   adapter test, not as a retrospective safety label.
