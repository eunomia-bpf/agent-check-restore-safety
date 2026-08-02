# History-admission compiler

This directory is a dependency-free paper artifact for checking one typed
Fork, Restore, or Merge transformation.  It is deliberately not a checkpoint
engine and does not run an agent.  The compiler is an untrusted witness
synthesizer; the verifier independently rebuilds the finite semantics before
issuing a seal.

The input names an authority family, a monotone durable-receipt frontier, an
old admitted envelope, leaf future contracts, explicit target-cell identity
evidence, and the runtime's correlation-controller access relation.  The
compiler then:

1. arm-tags independent occurrences and folds only explicitly justified cell
   aliases;
2. derives the typed operator's choice/tensor candidate and required families;
3. computes the exact durable-prefix-safe subfamily;
4. classifies semantic admission as `Inherit`, `ReadmitOK`,
   `NeedsMechanism`, or pruning-only `Reject`;
5. checks deployment readiness separately by recomputing which futures the
   declared co-live controllers can asynchronously realize; and
6. checks the implementation relation
   `Required <= RawPhysical <= Admitted`, distinguishing exact realization from a
   safe restriction that omits only optional behavior; and
7. derives the canonical greatest co-liveness-only safe restriction as a
   non-authorizing repair proposal, including declared-product required
   coverage and any missing required configurations; and
8. emits a structural certificate or a compact prefix, lineage, forbidden
   union, gate-cut, or gate-clone witness.

Semantic admission and deployment readiness are intentionally separate.
`NeedsMechanism` says the complete candidate needs pruning; when the submitted
controller manifest already satisfies `Required <= RawPhysical <= Admitted`,
it supplies that restriction and receives `ReadyWithRestriction`.  Otherwise
the result remains diagnostic.  `Inherit`, `ReadmitOK`, or `NeedsMechanism` is
structurally eligible only when the independently verified manifest sandwich
holds.  The verifier emits a
`history_admission` seal, not an effect-authorization credential.  It always
sets `effect_authorizes` to false and lists the runtime obligations that remain,
including manifest authenticity, co-liveness coverage attestation, complete
mediation, controller freshness, atomic redemption, and refinement between the
declared controller product and the runtime's actual behavior.  `Reject` is
always diagnostic.

The request schema is version 2; result and verification schemas are version
3.  Request version 2 makes `operation.controller_future_coverage` mandatory.
Result version 3 retains the version-2 coverage/readiness fields and adds the
canonical `co_liveness_repair` proposal described below.  The verifier schema
is bumped because it now authenticates that additional result surface.

## Quick start

From `artifact/`:

```sh
python3 -m history_admission.compiler \
  fixtures/history_admission/inherit_choice.json \
  --output /tmp/history-admission-result.json
python3 -m history_admission.verifier \
  fixtures/history_admission/inherit_choice.json \
  /tmp/history-admission-result.json \
  --output /tmp/history-admission-seal.json
python3 -m unittest -v test_history_admission
```

Both programs reject duplicate JSON keys, floats, unknown fields, missing
receipt bindings, nonmonotone receipt phases, undeclared reuse of a stable cell
anchor, an alias that changes the commitment or effect binding, silently
inactive declared controllers, and inputs beyond the finite analysis caps.  A
verified `Reject` is a valid diagnostic result and exits successfully;
malformed input or an invalid certificate exits nonzero.  An arm marked
`sound_overapprox` yields a conservative result relative to that declared
overapproximation; the result records this precision explicitly.

## Co-liveness contract and observation arity

`operation.controller_future_maxima` is the maximal-configuration syntax for
the controller co-liveness family Gamma.  The parser takes its downward
closure, so the resulting family is nonempty, contains the empty
configuration, and is downward closed.  Here co-live means that the named
controllers can contribute to one co-durable configuration during the same
fixed-prefix admission epoch.  It is not limited to simultaneous processes:
sequential contributors before a mandatory receipt-frontier recheck belong in
the same contract.  Receipt-frontier growth starts a new decision.

`controller_future_coverage` is an adapter attestation, not a fact inferred by
the compiler or verifier.  `exact` says the submitted family is the complete
runtime co-liveness family for that epoch.  `sound_overapprox` says it contains
every actually co-live controller set, while allowing extra sets.  A truthful
overapproximation preserves the upper safety check but may conservatively
request coordination or reject; it does not establish that every required
future is implementable.  The latter remains the separate
`runtime_required_coverage` obligation.  In either mode, the parser checks only
the enum value.  The runtime adapter must establish the attestation and the
`Actual <= RawPhysical` relation.

In particular, a list of pairwise projections is not a complete Gamma for a
runtime in which three controllers may contribute before the next prefix
recheck.  Such a runtime may not label that projection `exact`; nor is the
projection a sound overapproximation.  The prototype consumes the full
declared Gamma (or a sound overapproximation of it) when constructing
`RawPhysical`.

For every non-`Reject` decision, the result also reports
`coordination.required_coliveness_arity`:

```text
r* = max(max{|x| : x in Required},
         max{|m| : m is a minimal nonface of Admitted},
         1 if a target cell is outside support(Admitted), else 0).
```

This contract-derived number is an engineering diagnostic: it bounds the size
of controller groups whose nonempty local contributions may be relevant to a
required configuration or an admitted-family obstruction.  For example, the
`U(2,3)` fixture reports `r*=3`, even though every pair is admitted, because
its only minimal nonface is the triple.  `Reject` reports `null` because there
is no admitted deployment family.  The current prototype neither uses `r*` to
truncate Gamma nor accepts an `r*`-wise projection in place of full coverage.
The Lean development proves that complete projections through `r*` preserve
readiness (under fixed access, fixed downward-closed local families, and
downward-closed co-liveness), as well as an arbitrary-arity lower bound; the
executable deliberately retains the simpler full-family interface.

## Canonical co-liveness-only repair

For each non-`Reject` decision, `co_liveness_repair` filters the declared full
co-liveness family without changing any controller's local permission family.
Writing `E_i` for controller `i`'s downward-closed local family and `A` for
`Admitted`, it computes

```text
Gamma* = { C in Gamma | tensor(i in C, E_i) <= A }.
```

The parser constructs every `E_i` from at least one maximum, so each local
family is nonempty and contains the empty configuration.  Therefore, whenever
`H <= C`, every product choice for `H` is also a product choice for `C`: the
controllers in `C - H` choose empty.  Hence
`Product(H) <= Product(C)`.  Together with downward closure of declared
`Gamma`, this makes `Gamma*` hereditary and the unique greatest subfamily of
declared `Gamma` whose controller product respects `A`; it is the executable
counterpart of the Lean powerset `SafeGroup` filter.  The result emits its
canonical `restriction_maxima`.  It also obtains the physical product under
`Gamma*` from the same globally capped product pass, reports
`required_coverage.covered_maxima`, and lists every exact `missing_required`
configuration rather than taking the downward closure of that generally
non-downward-closed difference.

The status is `not_needed` when the declared Gamma is already safe and covers
the required family, `feasible` when a strict Gamma restriction is safe and
still covers every required configuration, and `infeasible` when no
co-liveness-only restriction can retain declared-product required coverage.
Only `feasible` sets `installation_required` to true.  A local overpermission
can therefore be diagnosed as infeasible: preventing controllers from being
co-live cannot repair a forbidden choice made by one controller while still
retaining behavior that needs that controller.

This object is an offline proposal, not an installed policy.  It always sets
`effect_authorizes` to false and does not alter the submitted manifest,
`deployment.readiness`, `history_admission.structurally_eligible`, or the
verifier's seal kind.  The runtime must install the restriction and submit a
new manifest before it can affect readiness.  With `sound_overapprox`, the
proposal safely filters the declared upper bound, but its required-coverage
claim remains explicitly scoped to `declared_controller_product`; it cannot
prove `Required <= Actual`.  `Reject` has no `Admitted` family and therefore
reports `co_liveness_repair: null`.

## Proof crosswalk and scope

The implementation mirrors the Lean definitions `familyChoice`,
`familyTensor`, `safeFuture`, `StructuralRefinement`, and
`classifyAdmission_sound`.  The prototype recomputes the canonical decision on
every request and reports structural-inheritance eligibility; it does not take
a prior verification seal or implement certificate-chain reuse.  Minimal
nonfaces and coordination components mirror the exact partition result.
`ControllerCoverAdmission.lean` mechanizes the
overlapping access-relation extension: raw and support-restricted controller
products, the exact obstruction criterion, the three failure causes,
runtime-family refinement, and reduction to the older functional partition
through a proved canonical adapter.  The executable `GateClone` subtype still
uses manifest origin metadata; Lean mechanizes the underlying locally sound
`CorrelationCut`, not origin provenance.

This is a theorem-to-implementation crosswalk, not a verified extraction.  The
Lean development does not prove that the Python parser implements a formal
`ManifestWF` predicate or that both programs compute definitionally identical
families.  Compiler/verifier agreement, strict parser tests, the exhaustive
small-family oracle, and proof replay are separate evidence layers.

Cell identity, lineage/lease transport, and controller identity are three
separate checks.  An alias requires the same stable cell anchor, authority atom,
commitment key, and effect-binding digest; conflicting parent or lease claims
do not invalidate that identity proof, but disable structural inheritance and
force readmission or revalidation.  Conversely, two gate uses may reach the
same aliased cell while still naming distinct controller anchors.

The raw-physical-family calculation treats controller anchors declared co-live as
independently product-composable.  A runtime with a hidden shared ratifier must
represent it as one authoritative controller or supply a stronger joint
contract; co-liveness alone is not an exploit proof.  `GateClone` and `GateCut`
are precise witnesses under this independent-product abstraction.

For the deterministic product cover carried by a reported witness, unsafe
products are split into three theorem-backed causes. `OutsideSupport` means a
controller exposes a cell absent from admitted support;
`LocalOverpermission` means one controller alone exposes a minimal nonface of
the admitted family; and `CorrelationCut` means every chosen local configuration is
admitted but their union is not.  Only the last class is emitted as a
`GateClone` or `GateCut`.  Different valid covers of the same bad physical
configuration may expose different causes; the tool does not claim a globally
unique root cause.

The model-level check is `Required <= RawPhysical <= Admitted`.  If `Actual` is
the runtime family, deployment correctness additionally requires
`Required <= Actual <= RawPhysical <= Admitted`.  The verifier cannot infer the
relations involving `Actual` from a manifest, so it records runtime soundness
and required coverage as external obligations.

The seal is conditional on the manifest being a truthful, completely mediated
runtime abstraction.  This artifact does not authenticate receipts or leases,
infer natural-language intent, prove external exactly-once execution, or prove
that an unmodified Claude/Codex runtime realizes the supplied contracts.
