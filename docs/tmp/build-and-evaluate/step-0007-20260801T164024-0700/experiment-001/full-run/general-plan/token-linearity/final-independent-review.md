# Final independent review of the Lean token strengthening

Date: 2026-08-01 (America/Vancouver)

## Verdict

**ACCEPT the paper-facing fixed-plan-epoch formal package under its stated
premises and non-goals.**

The source-derived strengthening is real and closes the most important issue in
the previous independent review.  The actual-`rho` atom is executable and
sound/complete; canonical and both Merge targets have exact current-fiber
characterizations; transfer, Prepare, Restriction, and Revoke now have genuine
source-derived linearity proofs; the local-first defended gates are proved
extensionally equal to the old full-target gates and bridge to the semantic
grammar; and existing `OperationTokenBound` facts are preserved both per step
and through RTC with the necessary `TokenSafe` premise.

The main token-safety theorem survived every attempted attack.  In particular,
a malformed transfer can change a historical origin, but the real transfer
checker rejects it; a valid transfer cannot put a durable bound claim in
`rho`; an omitted source fiber is a deliberate withdrawal, not duplication;
and no `TokenPositiveTrace` edge can mint an initial token.

The final incremental revision closes both blockers from the preceding review:

1. **The generic theorem is now authoritative.**
   `afterTransfer_nonAmplifying_iff_target_current_linear` has exactly the
   generality exercised by the earlier independent replay: it assumes only that
   the target remaining set is the actual transfer's computed child batch.
   The canonical, simulation-Merge, and direct-Merge iff theorems are now
   one-line corollaries of that result.

2. **The paper-facing audit inventory and prose boundary are now closed.**
   `Audit.lean` explicitly checks and prints the generic theorem and the
   formerly omitted checker, trichotomy, completeness, zero-demand, lifecycle
   projection, and version-monotonicity results; `audit.sh` freezes them.  The
   paper now calls weighted accounting a token-spec promise projection and
   explicitly says that optional `WitnessCoherent` is a one-state bridge, is
   not derived from safety, and is not trace-preserved.

The earlier coherence counterexample remains important, but it now attacks a
claim the paper explicitly does not make: the algebraic weighted projection is
not presented as reachable actual current/bound claim demand or as a refinement
of the old claim-indexed `FullPlanInvariant`.

## Scope and method

I read in full:

- `PlanTokenStrengthening.lean`;
- `TokenWeightedAccounting.lean`;
- `PlanTokenLinearity.lean`;
- `Plan.lean`;
- `Audit.lean`, `Main.lean`, and `scripts/audit.sh`;
- the strengthening report; and
- the preceding independent review and its review-only Lean witness.

I also inspected the relevant `Transfer`, plan-invariant, and old
`FullPlanInvariant` definitions needed to attack the premises.  No raw private
trace was read.  No repository source or paper file was edited, and no Git
operation was run.

The full authoritative audit was rerun, including the fresh checker.  A new
review-only Lean file outside the repository tested a generic theorem and the
specified counterexamples.  Its sanitized results are in
`final-independent-validation.log`.

## 1. Actual-`rho` local atom

### What is established

`transferCurrentFiber S tr t` is computed from exactly:

- `Plan.childBatch tr S.controller.plan.remaining`;
- the source origin ledger; and
- `TokenLedger.transportedOrigin tr`, hence the actual `tr.rho`.

It does not read a caller-proposed target set, target lifecycle state, or a
demand coordinate.  `TransferTokenNonAmplifying` bounds the cardinality of
this fiber by one for every token in `S.ledger.initial`.

The executable check has both directions:

- `checkTransferTokenNonAmplifying_sound`;
- `checkTransferTokenNonAmplifying_complete`.

Both are unconditional finite-checker facts.  The preservation theorem later
uses source `LinearValid.current_covered` to ensure that every source current
claim's origin lies in the checked initial set.

### Generic theorem now in the authoritative module

`afterTransfer_currentFiber_eq` proves the exact generic equality for any
controller target whose remaining set is the standard computed child batch.
The authoritative module now derives:

```text
TransferTokenNonAmplifying S tr
  iff
for every initial token, the current fiber of
  TokenState.mk controller' (ledger.afterTransfer controller' tr)
has cardinality at most one
```

under only:

```text
controller'.plan.remaining = childBatch tr source.plan.remaining.
```

The proof compiled and depends only on `propext` and `Quot.sound`.  I also
independently replayed the same proof without invoking the new generic theorem;
that replay passed with the same dependency set.  The following results:

- `canonical_nonAmplifying_iff_target_current_linear`;
- `simulationMerge_nonAmplifying_iff_target_current_linear`; and
- `directMerge_nonAmplifying_iff_target_current_linear`

are now direct `simpa` corollaries of
`afterTransfer_nonAmplifying_iff_target_current_linear`, parameterized by
`controller'` and the computed-remaining equality.  This is the desired
principle-level contribution rather than three unrelated API facts, and it is
included in both audit layers.

### Exact scope of the iff

The iff characterizes only target **current-fiber cardinality over the initial
tokens**.  It is intentionally not equivalent to all of target `LinearValid`:
coverage, bound-fiber linearity, current/bound exclusivity, and exact stored
disposition come from separate source/transport facts and reclassification.
The paper should say “target current-token linearity,” not “the complete target
token invariant.”

## 2. Source-derived transfer theorem

`afterTransfer_preserves_linearity_source` is now a genuine derivational
theorem.  It assumes:

- computed target remaining equality;
- stable target/source `opClaim`;
- source lifecycle `LWF`;
- `Transfer.CoreValid` for the actual `rho`;
- source `LinearValid`; and
- the transfer-local non-amplification atom.

It accepts neither target `LinearValid` nor target `checkLinear`.

The proof reconstructs all six fields:

- current coverage follows the child-batch witness back through `rho` and
  source coverage;
- binding coverage uses source `opClaim` plus durable-origin stability;
- current linearity is exactly the local atom;
- binding linearity follows from equality of actual binding fibers;
- exclusivity maps a target current witness back to a source current witness;
  and
- disposition exactness is definitional after `reclassify`.

Canonical and both Merge source gates correctly obtain `CoreValid` from their
real operation checkers.  They do not accept a topology certificate or target
invariant from the caller.

This closes the previous review's central objection.  The old target-only
theorems remain in `PlanTokenLinearity`, but the paper can now cite the
source-derived family, provided it states the premises.

## 3. Defended operational gate versus semantic grammar

The operational defended gates evaluate:

1. the existing plan/operation admission;
2. the actual-`rho` local atom; and
3. the complete target `checkLinear` scan.

The following equalities are correct:

- `checkCanonicalTokenDefended_eq_tokenPlan`;
- `checkSimulationMergeTokenDefended_eq_tokenPlan`;
- `checkDirectMergeTokenDefended_eq_tokenPlan`.

They prove that the local-first gate accepts exactly the same inputs as the old
base-plus-full-target gate.  This is expected: target `checkLinear` implies
target current linearity, the exact iff recovers the local atom, and checker
completeness converts it back to the Boolean.

The three `checked*Defended_token_step` theorems then map a successful defended
gate into the existing `TokenPositiveStep` grammar.  The mapping is sound.

The exact paper-safe wording is:

> The operational gate explicitly executes the local atom and the full target
> scan; it is extensionally equal to, and has a proved bridge into, the
> semantic grammar.

The following stronger wording remains false:

> Every old `TokenPositiveStep` constructor syntactically stores both checks or
> their execution order.

The old constructor still stores only the target Boolean.  This is an
operational/semantic representation distinction, not a safety defect.

### Source validation remains an explicit premise

The defended Boolean itself does not check source token linearity.  The
previous target-only repair witness still compiles: an invalid source with two
current witnesses can be restricted to one witness, and
`checkRestrictionTokenPlan` accepts the valid target.  Correspondingly,
`TokenPositiveStep` can be constructed from an invalid token source for some
operations; RTC safety begins from `TokenSafe`.

This does not refute any stated theorem.  It means the runtime algorithm's
“validate the loaded source, treating failure as trusted-store corruption” is
load-bearing.  The paper and implementation contract must not imply that a
mutating operation Boolean alone repairs or authenticates an arbitrary loaded
ledger.

An optional hardening is one top-level monitor gate that checks source
`checkLinear` before dispatching the operation-specific gate.  The formal
theorem can continue to assume `TokenSafe`; the runtime should make the source
check unavoidable.

## 4. Prepare, Restriction, and Revoke

### Prepare

`prepare_preserves_linearity_source` derives target linearity from source
`LinearValid` and actual `Plan.AssignmentValid`; it does not use the target
scan.  The proof correctly separates all combinations of new and existing
bindings:

- new/new uses source current-token uniqueness and assignment injectivity;
- new/old and old/new contradict source current/bound exclusivity; and
- old/old uses source binding-token uniqueness.

It also proves that a surviving current witness cannot be a prepared head
claim.  Reclassification makes the target disposition exact.

`prepare_binding_new_or_preserved` correctly states a structural case split:
each target `opClaim` is either supplied by the current assignment or is an
unchanged source binding when that operation is unassigned.  It is not, by
itself, a freshness theorem.  Freshness comes from the admitted assignment and
the actual `PreparePlanned`/`Step` relation.

The existing-operation continuity theorem correctly applies only to bindings
present before Prepare.  Newly prepared operations are handled as new; they
are not incorrectly assumed to have existed in the source.

### Restriction and Revoke

`reclassify_preserves_linearity_of_subset` is an appropriate generic lemma:
current fibers only shrink, `opClaim` and origins remain fixed, and disposition
is recomputed.  `restriction_preserves_linearity_source` and
`revoke_preserves_linearity_source` instantiate it with actual computed
remaining-set subset lemmas.  No target scan is used.

These three source-derived cases are technically sound.

## 5. Durable operation origin and RTC

The global application of `transportedOrigin` to every claim ID was attacked
again.  Without transfer validity it really can drift: the review-only witness
maps claim 0 to a different claim whose ledger origin is another token, and
`afterTransfer` changes claim 0's origin.  The real transfer checker rejects
that witness because the purported source is not tentative.

Under the actual premises, the defense is complete:

```text
opClaim e = some c
  -> LWF.bound_durable: status(c) = durable
  -> CoreValid/provenance: rho(c) = none
  -> transportedOrigin(c) = source origin(c).
```

This is exported by:

- `bound_durable_rho_none`;
- `bound_durable_origin_afterTransfer`; and
- `afterTransfer_bindingFiber_eq`.

`OperationTokenBound S e c t` couples the actual lifecycle binding and its
ledger origin.  Its preservation is correctly proved by:

- `tokenPositiveStep_preserves_existing_operation_token`; and
- `token_positive_trace_preserves_existing_operation_token`.

Both require the appropriate source facts; in particular the RTC theorem
requires `TokenSafe S`.  That premise is essential and must appear in the
paper's formal theorem statement.  The conclusion is logical binding/origin
continuity, not physical exactly-once execution.

## 6. Missing `rho` coverage attack

An all-`none` transfer was checked in the review-only suite.  It satisfies the
core transfer checker and the local token atom, has no child batch, and has no
target current token witness.  Reclassification marks the original token
withdrawn.

This is the intended semantics:

- non-amplification is a safety condition, not a progress/coverage condition;
- a source token may have zero surviving current witnesses;
- a missing source fiber therefore means withdrawal, not resurrection or
  duplication.

No counterexample was found.  If the paper needs a liveness theorem saying a
specific kind of Fork must preserve some work, that is a separate operation
admission obligation and not part of token non-amplification.

## 7. Fixed epoch and dynamic mint attack

`TokenPositiveStep.initial_eq` is definitional for every constructor, and
`within_plan_epoch_initial_tokens_fixed` correctly lifts it through RTC.
`EpochToken` qualifies identity by `(epoch, serial)`, and
`trace_initial_token_same_epoch` correctly derives the installed epoch from
`TrustedPlanEpochStart` plus the fixed initial set.

There is no in-trace dynamic mint hole.

There is also no cross-epoch mint theorem.  `TrustedPlanEpochStart` is an
explicit trust boundary with only:

- source `TokenSafe`; and
- equality of the source initial set with `spec.initial`.

It does not contain an `everIssued` set, authorization for new weights, a CAS
epoch transition, freshness against prior starts, or reconciliation of
prepared work.  Two independent trusted starts can reuse the same epoch/token
identity because no theorem relates them.  This is not a counterexample to the
within-epoch theorem; it is a confirmed non-goal.

Paper-safe wording:

> Initial token identities and their external specification are fixed within
> one trusted plan epoch.  Authorization, global freshness, and rollover are
> assumed at installation and are not proved.

## 8. Identity and weighted projections

### Correct narrow result

For any total `TokenDisposition`, the following are correct:

- `PlanEpochSpec.cardinality_partition`;
- `PlanEpochSpec.weighted_partition_exact`;
- `PlanEpochSpec.zero_weight_token_visible`.

`LinearValid.token_trichotomy` supplies the stronger identity interpretation:
remaining has exactly one current witness, prepared has exactly one bound
operation, and withdrawn has neither.  `UnifiedProjection` packages installed
identity, cardinality, and weighted projections.  From
`TrustedPlanEpochStart`, `trace_preserves_unifiedProjection` reconstructs this
package at every endpoint.

The zero-vector result is valid but simple: its `_zero` premise is unused
because every initial token is present in one disposition partition regardless
of weight.  Its value is explanatory—identity survives even when every weight
coordinate contributes zero—not an additional conservation mechanism.

### Counterexample: external spec is not controller reality

I constructed the same token ledger with two external `PlanEpochSpec` values:
one assigns weight 0 and one weight 7 to the same installed identity.  Both
satisfy their own `B+E+W=P` theorem.  The weight-7 spec is not coherent with the
actual zero-demand current claim.

This is expected because weighted exactness is algebraic over an arbitrary
external spec.  `TrustedPlanEpochStart` does not require `WitnessCoherent`.

### Stronger counterexample: coherence is not preserved by an admitted trace

The fresh review constructed a source with:

- one current token, root slot 0, weight 1, actual demand 1;
- controller `Safe`;
- token `LinearValid` and hence `TokenSafe`;
- full `WitnessCoherent` (bound clauses are vacuous initially); and
- a valid trusted epoch start.

A real parallel-Fork transfer retains exactly one child, so the local atom
holds, but gives that child demand 0.  This is legal because
`Transfer.CoreValid.fiber_demand` requires only

```text
sum(child demand) <= source demand.
```

The defended canonical checker evaluates to true.  Its bridge yields an actual
`TokenPositiveStep`; the one-edge RTC theorem yields `UnifiedProjection` at the
target.  Nevertheless the target is not `CurrentWitnessCoherent`, because its
current claim demand is 0 while the immutable token weight is 1.

This proves precisely:

```text
UnifiedProjection spec target
does not imply
CurrentWitnessCoherent spec target.
```

It also shows that even assuming full `WitnessCoherent` initially does not make
it a trace invariant under the current transfer semantics.

### Design choices

There are three honest options:

1. **Promise interpretation (smallest change):** define coherence as actual
   demand `<=` token weight, keep root equality, and prove it through all steps.
   Then token-weighted `B/E/W/P` are promised envelopes, not exact actual load.
2. **Exact-load interpretation:** strengthen transfer admission so the one
   surviving token witness keeps exactly the token weight, or explicitly split
   residual weight into withdrawal metadata.  This changes the accepted
   semantics and needs new proofs.
3. **Paper-only scope reduction:** retain current Lean unchanged and describe
   weighted accounting only as an immutable token-spec/disposition projection.
   Do not say it equals actual current/bound controller load at all reachable
   states.

The strengthening report currently chooses option 3, which is formally
honest.  The paper must do the same unless additional theorems are added.

### Old `FullPlanInvariant`

No theorem connects `TokenWeightedAccounting` to the older
`FullPlanInvariant`:

- the states and dispositions are different;
- old `B` is claim-indexed actual batch demand;
- old `E`, `W`, and `P` are schedule/ledger rows;
- token-weighted values are sums of arbitrary external token metadata; and
- `WitnessCoherent` is neither derived from old `Coherent` nor preserved.

This disconnection is explicitly documented in the new module and is a valid
non-goal.  Any paper phrase implying a proved equality or refinement between
the two ledgers is unsupported.

## 9. Audit and fresh-checker results

The complete authoritative command passed with exit 0:

```text
cd lean
scripts/audit.sh
```

It completed:

- placeholder and project axiom/constant scans;
- the frozen inventory;
- the 8504-job full library build;
- `Audit.lean` dependency replay;
- rejection of `sorryAx` and non-whitelisted dependencies; and
- `leanchecker --fresh AuthorityContinuity.Main`.

The only permitted dependencies observed were:

- `propext`;
- `Quot.sound`; and
- `Classical.choice`.

`Audit.lean` now correctly imports both strengthening modules; `Main` imports
the audit root, so the previous root-reachability defect is fixed.

### Frozen inventory closure

The final audit root contains 71 paired `#check`/`#print axioms` entries, and
the script freezes 65 core theorem names plus its executable controls.  Static
replay confirmed that every frozen name is declared and has a dependency
record in the final audit log.

In particular, both layers now include the new generic transport theorem and
the previously omitted paper-facing token results:

- `PlanTokenLinearity.TokenState.checkLinear_sound`;
- `PlanTokenLinearity.TokenState.LinearValid.token_trichotomy`;
- `PlanTokenStrengthening.checkTransferTokenNonAmplifying_complete`;
- `ZeroDemandRegression.zero_demand_parallelFork_rejected` and
  `duplicated_token_fiber_cardinality`;
- `token_positive_trace_projects_actual`; and
- `token_positive_trace_version_mono`.

Their final logged dependencies all lie in the permitted set.  The earlier
inventory blocker is therefore closed.

## 10. Paper-usable theorem mapping

| Paper-level statement | Lean result | Exact qualification |
|---|---|---|
| Finite full token checker is sound | `TokenState.checkLinear_sound` | Soundness only; now frozen and audited |
| Each initial token is remaining/prepared/withdrawn with exact fiber counts | `LinearValid.token_trichotomy` | Requires source/state `LinearValid`; now frozen and audited |
| Actual-`rho` local Boolean matches its proposition | `checkTransferTokenNonAmplifying_sound`, `_complete` | Iterates initial tokens; both directions are frozen and audited |
| Local atom exactly characterizes computed target current-fiber linearity | `afterTransfer_nonAmplifying_iff_target_current_linear` plus three operation corollaries | Generic iff requires only computed remaining equality; it is not complete `LinearValid` |
| Valid transfer preserves complete token linearity from source facts | `afterTransfer_preserves_linearity_source` | Requires computed remaining, stable `opClaim`, `LWF`, `CoreValid`, source `LinearValid`, local atom |
| Operational local-first+full gate matches semantic accepted language | three `check*Defended_eq_tokenPlan` and three `checked*Defended_token_step` theorems | Old constructor does not record check order |
| Prepare preserves token linearity from source | `prepare_preserves_linearity_source` | Requires source `LinearValid` and actual `AssignmentValid` |
| Restriction/Revoke preserve by monotone drop | `restriction_preserves_linearity_source`, `revoke_preserves_linearity_source` | Token linearity only; operation safety comes from the base grammar |
| Arbitrary checked history preserves safety | `token_positive_trace_preserves_source_decomposed` | Requires `TokenSafe` at trace source; one-way checked sublanguage |
| Existing durable operation keeps claim and token | per-step and RTC `*_preserves_existing_operation_token` | Requires initial `OperationTokenBound`; RTC also requires source `TokenSafe`; says nothing about physical exactly-once |
| Prepare bindings are new or unchanged old bindings | `prepare_binding_new_or_preserved` | Structural case split; admitted assignment supplies freshness |
| No in-epoch history step mints tokens | `within_plan_epoch_initial_tokens_fixed` | Within one `TokenPositiveTrace` only; no cross-epoch theorem |
| Installed token identities remain in one epoch | `trace_initial_token_same_epoch` | Requires `TrustedPlanEpochStart`; installation/global freshness trusted |
| Identity/cardinality and weighted spec partitions hold at every endpoint | `trace_preserves_unifiedProjection` | Token-spec/disposition projections only; no actual-load or old-FullPlan coherence |
| Current/bound witness agrees with spec, if assumed | `current_witness_matches_spec`, `binding_witness_matches_spec` | Consequences of optional `WitnessCoherent`; not derived and not trace-preserved |
| Zero-demand duplicate Fork is separated | `zero_demand_parallelFork_rejected`, `duplicated_token_fiber_cardinality` | Closed regression; both are frozen and audited |
| Trace projects to actual lifecycle and version is monotone | `token_positive_trace_projects_actual`, `token_positive_trace_version_mono` | Both are explicitly frozen and audited |

## 11. Resolved revisions and remaining optional work

### Resolved before final ACCEPT

1. **Frozen claim inventory:** the formerly omitted paper-facing token results
   and generic transport theorem are now checked, dependency-printed, and
   frozen; the full audit exits 0.
2. **Weighted wording:** the paper calls the result a token-spec promise
   projection and expressly disclaims actual-load, old-FullPlan, and
   trace-preserved-`WitnessCoherent` interpretations.
3. **RTC source premise:** the paper states source `Safe`, which is stronger
   than the mechanized `TokenSafe` premise needed for existing operation-token
   preservation.
4. **Source validation:** the monitor algorithm explicitly validates the
   loaded source, and the checked-history theorem starts from source safety.
5. **Generic transport law:** the authoritative theorem now factors all three
   operation-specific iff results.

### Optional strengthening

1. If token weights are later intended to represent reachable actual bounds,
   introduce a preserved upper-bound relation and prove it per step/RTC.
2. Add one combined theorem showing that a trusted start plus a defended
   operational edge yields the semantic edge and endpoint token safety.  The
   ingredients exist; the theorem would make the implementation contract
   easier to cite.
3. For maximum editorial clarity, replace the isolated phrase “Weighted demand
   of the three classes” in the security-goal paragraph with “token-spec
   promised weights of the three disposition classes.”  The formal definition
   and surrounding prose already make the intended meaning clear, so this is
   not a correctness blocker.

### Confirmed non-goals, not blockers if stated

- dynamic mint and epoch rollover;
- global freshness across trusted starts;
- liveness/coverage of every source token under `rho`;
- equality/refinement with old `FullPlanInvariant`;
- physical exactly-once external effects;
- concurrent storage linearizability; and
- converse mediation of arbitrary raw runtime events.

## Final assessment

The strengthened Lean development now supports the paper's most interesting
principle: an actual history transfer may change claim witnesses, but it cannot
amplify one initial authority occurrence, and a durable operation's existing
claim/token identity remains stable through arbitrary checked histories.

That core is nontrivial and should be accepted.  The generic transport law is
now explicit, the paper-facing theorem inventory is audited, and the prose no
longer presents the algebraic weighted projection as a proved reachable
actual-load invariant.  I found no remaining formal or claim-alignment blocker
in this increment.
