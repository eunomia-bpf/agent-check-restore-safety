# Typed History Admission And Structural Binding Transport

Date: 2026-08-02

## Question

Can a history-transforming runtime derive an authority-relevant future from
the *kind* of Fork, Restore, or Merge, transport an existing certificate when
the change is structural, and otherwise give an exact fixed-frontier decision
between full readmission, required-preserving mechanism repair, and rejection?

This step deliberately does not implement a checkpoint engine or claim that a
real Claude/Codex runtime already realizes the abstract future family.

## Model added

`AuthorityContinuity/TypedHistoryAdmission.lean` adds three linked layers.

1. A finite family algebra distinguishes exclusive choice (`union`) from
   joint durability (`tensor`, the family of pairwise configuration unions).
   Both constructions preserve downward-closed well-formedness.
2. Six typed operators derive operator-level `candidate` and `required`
   families from leaf contracts:
   `forkChoice`, `forkParallel`, `restoreReplace`, `restoreLive`,
   `mergeSelect`, and `mergeJoin`.
3. A versioned admitted envelope and structural refinement transport a fixed
   durable prefix, future configurations, and lineage.  Refinements compose,
   so an online execution chain can be certified edge by edge without
   enumerating its eventual graph.

The target-cell type is a namespace of globally normalized semantic
commitment occurrences.  It is not a namespace of resources or physical
controllers.  Independent cross-arm occurrences must receive distinct IDs
(normally by arm tagging); the same ID in both arms denotes one deliberately
shared obligation.  Identity normalization and intentional-alias evidence are
adapter obligations, not inferred by the family algebra.

## Checked decision boundary

For a valid operation, `required` is well formed and is a subset of
`candidate`.  At a fixed authority family, durable prefix, and lineage:

- `FullReadmit` checks the whole generated candidate.
- `NeedsMechanism` means all required configurations survive the exact prefix
  filter but at least one optional candidate does not.
- `PruningReject` means no subfamily between `required` and `candidate` has a
  prefix-transport certificate.

`op_admission_trichotomy` proves both coverage and pairwise exclusivity.  The
valid-contract premise is necessary: without `required <= candidate`, a
malformed contract can be fully safe while simultaneously demanding an
outside behavior that no pruning preserves.

The semantic classifier exposes the four obligations planned for the tool:

- `Inherit`: a version-monotone structural refinement exists and preserves the
  declared required family;
- `ReadmitOK`: inheritance is unavailable, but the full prefix check succeeds;
- `NeedsMechanism`: required behavior survives only after installing a
  synthesized fence/pruning/coordination change;
- `Reject`: no pruning-only repair preserves the required family.

`classifyAdmission_sound` proves the meaning of every enum result.  The Lean
classifier is intentionally noncomputable and proof-free.  It is a semantic
proof-obligation skeleton, not yet the executable witness compiler.  The enum
also does not assert deployment readiness: even `Inherit` or `ReadmitOK` needs
a separately verified concrete controller partition.  A missing or cut gate is
nonauthorizing although the abstract candidate family may be fully safe.

## Structural lease-binding scope

The minimal `Lease` object records only issued version, source cell, and source
atom.  A refinement witness transports that binding to an active target cell,
preserves the lineage equation, and proves the active atom is not already in
the durable prefix.  The result is therefore *structural lease-binding
transport*.  It does not prove issuer/root/scope/digest/expiry/signature
authentication, revocation, or that a concrete token can be reused unchanged.

## Separating fixtures

Two fixtures use the same leaf contracts and change only the typed operator.

- Choice produces `{}, {left}, {right}` and inherits an exclusive source
  certificate.
- Parallel additionally requires `{left,right}`; identity lineage into an
  exclusive source has no structural refinement and no required-preserving
  pruning.

The shared-binding fixture transports one old binding to either of two
mutually exclusive target cells.  Those cells must share a logical
coordination domain; split local controllers product-compose the forbidden
pair.  Changing only Choice to Parallel makes the shared lineage locally
noninjective and makes the joint required behavior pruning-only impossible.

This separates three facts that per-resource clone flags conflate:

1. target occurrence identity and source-atom lineage;
2. which occurrences may coexist durably;
3. which correlation gate prevents locally allowed pieces from recombining.

## Novelty boundary

The following are supporting mathematics, not standalone novelty claims:

- finite union/tensor family algebra;
- configuration-morphism composition and local injectivity;
- set filtering and by-cases classification;
- static minimal-nonface factorization from the preceding step.

The larger candidate contribution is the composition exposed to a concrete
runtime: typed history semantics generate the co-durability obligation;
durable receipts constrain readmission; structural lineage determines whether
old bindings transport; exact factorization determines the shared gate; and a
proof-producing compiler lowers the result or emits a minimal obstruction.
The current theorem step establishes the interface and separations but does
not yet establish that integrated compiler or a real-runtime refinement.

## Hostile review and repairs

The first review returned FAIL because the original exhaustive `Or` was not a
trichotomy for malformed contracts.  It also identified possible silent
cross-arm identity collapse and lease overclaiming.  The revision:

- added the valid-contract premise and a separate pairwise-exclusivity proof;
- added a four-way sound semantic classifier;
- documented normalized occurrence identity and arm-tagging requirements;
- scoped Reject to fixed-frontier pruning-only repair;
- consistently scoped the lease theorem to structural binding transport; and
- replaced `native_decide` fixture proofs so audited paper-facing results have
  no generated native axioms.

The second hostile review returned PASS and found no remaining Lean
correctness blocker.  It requires the future executable tool to check arm
tagging or declared aliases explicitly before claiming it rejects undeclared
aliasing.

## Validation

- Direct elaboration of `TypedHistoryAdmission.lean`: PASS.
- Integrated `lake build AuthorityContinuity.Main`: PASS (8,502 jobs).
- Direct `Audit.lean`: PASS; 145 theorem dependency blocks, with only
  `propext`, `Quot.sound`, and `Classical.choice`.
- Frozen-name checks for the new classifier and exclusivity theorems: PASS.
- Fresh `leanchecker --fresh AuthorityContinuity.Main`: PASS (exit 0, no
  diagnostic output).
- Hostile re-review: PASS.

## Next gate

Implement a small deterministic offline compiler and a separately invoked
verifier.  The input must include complete leaf contracts, normalized
occurrence IDs or explicit aliases, lineage, an admitted source envelope,
durable receipts, outstanding structural bindings, and the typed operator.
The compiler should emit one four-way outcome plus machine-checkable witnesses;
the verifier must recompute the family, prefix safety, coordination closure,
and structural equations and fail closed on omitted or oversized inputs.
