# Token-linearity strengthening report

Date: 2026-08-01

## Outcome

This pass replaces the weakest target-postcondition explanation of token
linearity with transition-local obligations and source-derived preservation
proofs, while retaining the complete target scan as defense in depth.  It
also adds a separate epoch-qualified, token-weighted accounting layer.

The implementation is in:

- `lean/AuthorityContinuity/PlanTokenStrengthening.lean`
- `lean/AuthorityContinuity/TokenWeightedAccounting.lean`

The paper-facing replay surface is extended in:

- `lean/AuthorityContinuity/Audit.lean`
- `lean/AuthorityContinuity/Main.lean`
- `lean/scripts/audit.sh`

No paper, adapter, or private-trace file was edited by this pass.

## 1. Actual-rho, demand-free non-amplification

`transferCurrentFiber S tr t` computes the target current witnesses of token
`t` directly from the selected source batch, the immutable source origin map,
and the actual transfer map `tr.rho`.  It does not inspect resource demand.

`TransferTokenNonAmplifying S tr` requires each initial token's computed
target fiber to have cardinality at most one.  Its executable checker has both
soundness and completeness theorems.

For canonical transfer, simulation Merge, and direct Merge, the local atom is
proved equivalent to current-fiber linearity of the exact computed target:

- `canonical_nonAmplifying_iff_target_current_linear`
- `simulationMerge_nonAmplifying_iff_target_current_linear`
- `directMerge_nonAmplifying_iff_target_current_linear`

The general theorem `afterTransfer_preserves_linearity_source` reconstructs
all of target `LinearValid` from source `LinearValid`, source `LWF`, transfer
`CoreValid`, stable `opClaim`, and this local atom.  It accepts neither target
`LinearValid` nor target `checkLinear` as a premise.

## 2. Source-derived operation cases

The following cases now have preservation theorems that do not use a target
linearity scan:

- Prepare: `prepare_preserves_linearity_source`, from assignment membership,
  freshness, injectivity, and source linearity.
- Restriction: `restriction_preserves_linearity_source`, by current-fiber
  subset and stable bound fibers.
- Revoke: `revoke_preserves_linearity_source`, by the same monotone-drop
  argument.

`tokenPositiveStep_preserves_linearity_source_decomposed` re-proves
preservation for the existing production grammar.  Prepare, Restriction, and
Revoke ignore their target scans.  Canonical and Merge use a successful full
scan only to recover the equivalent local non-amplification atom; their other
linearity fields are source-derived.  The corresponding RTC theorem is
`token_positive_trace_preserves_source_decomposed`.

## 3. Local-first defended gates and the existing grammar

The new canonical and Merge defended checkers execute:

1. the existing plan/admission checker;
2. the transfer-local non-amplification atom; and
3. the complete target `checkLinear` scan.

The following theorems prove these checkers extensionally equal to the old
base-plus-full-target checkers:

- `checkCanonicalTokenDefended_eq_tokenPlan`
- `checkSimulationMergeTokenDefended_eq_tokenPlan`
- `checkDirectMergeTokenDefended_eq_tokenPlan`

This equality is expected: a successful complete target scan already entails
the local atom.  The new gate exposes the transition reason and allows a
local-first implementation; it does not change the accepted language.

Three `checked*Defended_token_step` theorems connect execution of these gates
to the existing `TokenPositiveStep` grammar.  The old inductive constructors
still store only the target `checkLinear` evidence, not the explicit order in
which the operational gate evaluates its two token checks.  Therefore it is
accurate to say that the operational defended gate checks both and maps
exactly to the semantic grammar.  It would be inaccurate to say that the old
constructor syntax itself contains both premises.

## 4. Durable operation-token continuity

`bound_durable_origin_afterTransfer` exports the key transport fact: a claim
already bound to a durable operation lies outside a valid `rho` domain, so
its immutable origin token is unchanged.

`OperationTokenBound S e c t` couples the actual `opClaim e = some c` fact
with `origin c = some t`.  This pair is preserved by:

- every `TokenPositiveStep`:
  `tokenPositiveStep_preserves_existing_operation_token`;
- every `TokenPositiveTrace`:
  `token_positive_trace_preserves_existing_operation_token`.

Prepare is treated separately: `prepare_binding_new_or_preserved` proves
that every target binding is either a new assignment in that Prepare step or
an unchanged source binding.  The continuity theorem applies to bindings
that already existed at the source; it does not misclassify newly prepared
operations as old ones.

## 5. Epoch-qualified token-weighted accounting

`EpochToken` identifies a token by `(epoch, serial)`.  `PlanEpochSpec`
installs, at an explicit trusted boundary:

- one epoch;
- the immutable initial token set;
- an immutable root slot for each token; and
- an immutable resource vector for each token.

The mutable ledger partitions this fixed identity set by disposition into
remaining, prepared, and withdrawn tokens.  Two projections are proved over
that same partition:

- identity/cardinality partition;
- weighted partition `B + E + W = P`, for every root slot and coordinate.

`zero_weight_token_visible` makes the important zero-vector case explicit: a
token with weight zero in every coordinate remains present in exactly the
identity partition even though it is invisible to a weight-only sum.

`UnifiedProjection` packages installation, identity trichotomy, weighted
equality, and cardinality equality.  `tokenSafe_unifiedProjection` derives it
from `TokenSafe` plus installed metadata.  Starting from
`TrustedPlanEpochStart`, `trace_preserves_unifiedProjection` preserves
`TokenSafe` and reconstructs both projections at every RTC endpoint.
`trace_initial_token_same_epoch` proves every endpoint token still carries
the installed epoch.

## 6. Explicit boundaries

- The initial token set is fixed only *within a plan epoch*.
  `within_plan_epoch_initial_tokens_fixed` is not a theorem about dynamic
  minting or epoch rollover.
- `TrustedPlanEpochStart` is a specification/initialization boundary.  This
  pass deliberately does not add an incomplete dynamic mint transition.
- Root and weight metadata are immutable because the same external
  `PlanEpochSpec` parameter is used across the trace; they are not mutable
  ledger fields.
- The weighted theorem is an exact partition conservation theorem.  It does
  not prove monotonicity of individual `B`, `E`, or `W` components.
- No coherence with the older claim-indexed `FullPlanInvariant` rows is
  claimed.  `WitnessCoherent` is an optional, explicit assumption connecting
  token metadata to both current claims and durable bound claims;
  `current_witness_matches_spec` and `binding_witness_matches_spec` only
  expose consequences of that assumption.
- The local transfer atom governs target *current* witnesses.  Durable bound
  witnesses are handled by the separate `LWF`/`CoreValid` origin-stability
  argument.

## 7. Validation

The final audit command is:

```text
cd lean
PATH=/path/to/lean/toolchain/bin:$PATH scripts/audit.sh
```

It performs source placeholder/axiom scans, checks the frozen theorem and
control inventory, builds the full `AuthorityContinuity` library, replays
`Audit.lean`, rejects `sorryAx` and non-whitelisted kernel dependencies, and
runs a fresh replay from `Main`, which transitively includes
`PlanTokenStrengthening` and `TokenWeightedAccounting` through `Audit`.

Final status: **passed**.

- Full library build: passed (`8504` jobs).
- Frozen theorem/control inventory: passed.
- Source placeholder and project axiom/constant scans: passed.
- Paper-facing axiom audit: passed.
- Fresh kernel replay from `AuthorityContinuity.Main`: passed.

Permitted kernel dependencies observed before fresh replay are only:

- `propext`
- `Quot.sound`
- `Classical.choice`

Full command output is recorded in `strengthening-audit.log` in this
directory.
