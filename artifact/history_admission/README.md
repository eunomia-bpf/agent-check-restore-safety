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

The request schema is version 3; result and verification schemas are version
4.  Request version 3 adds the theorem-guided
`exact_projection_through_r` controller-evidence mode.  Result version 4
scopes the computed physical family, distinguishes declared from accepted
required coverage, and prevents a `sound_overapprox` from receiving a Ready
decision or structural seal.  The verifier independently authenticates this
surface.

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
inactive declared controllers, projection members above the independently
derived arity whenever an admitted family exists, and inputs beyond the finite
analysis caps.  A verified
`Reject` is a valid diagnostic result and exits successfully; malformed input
or an invalid certificate exits nonzero.  An arm marked `sound_overapprox`
yields a conservative result relative to that declared overapproximation.  A
controller family marked `sound_overapprox` is diagnostic only and can never
receive a structural seal.

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
overapproximation can prove upper safety when its whole product is admitted,
but `Required <= RawUpper` does not prove `Required <= Actual`; this mode now
returns `RequiresExactCoverage` when the upper bound covers `Required`, or a
definite coordination failure when even the upper bound does not, and never a
structural seal.  Any overpermission witness in this mode belongs to the
declared upper bound and is not evidence that `Actual` exercised it.

`exact_projection_through_r` says the submitted family is exactly
`Pi_{<=r}(Gamma)`, where the compiler and verifier independently derive `r`
from the required and admitted contracts.  The parser expands the submitted
maxima downward, and both executables reject any member above `r`; exactness
relative to the hidden full `Gamma` remains an adapter obligation.  Under the
Lean theorem's fixed-access, fixed-downward-closed-local-family, and
downward-closed-`Gamma` assumptions, this projection preserves both required
coverage and physical safety, and therefore preserves readiness.

In particular, a list of pairwise projections is not a complete Gamma for a
runtime in which three controllers may contribute before the next prefix
recheck.  It may be submitted as `exact_projection_through_r` only when the
submitted sets do not exceed the derived `r` and the adapter attests that the
list is the complete projection of the hidden downward-closed Gamma through
that `r`.  Calling such a list `exact` or `sound_overapprox` would describe a
different contract.

For every non-`Reject` decision, the result also reports
`coordination.required_coliveness_arity`:

```text
r* = max(max{|x| : x in Required},
         max{|m| : m is a minimal nonface of Admitted},
         1 if a target cell is outside support(Admitted), else 0).
```

This contract-derived number bounds the size of controller groups whose
nonempty local contributions can witness a required configuration or an
admitted-family obstruction.  For example, the `U(2,3)` fixture reports
`r*=3`, even though every pair is admitted, because its only minimal nonface is
the triple.  `Reject` reports `null` because there is no admitted deployment
family.  Version 3 uses this theorem operationally: the projection mode
enumerates only the submitted lower-order family.  Its `physical_maxima`
therefore has scope `exact_projection_lower_bound`; when readiness holds but
optional behavior is absent from that lower bound, status is
`ready_fidelity_unknown` and `exact_fidelity` is `null` rather than false.

## Canonical co-liveness-only repair

For each non-`Reject` decision, `co_liveness_repair` filters the submitted
co-liveness evidence without changing any controller's local permission
family.
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

Under `exact`, the status is `not_needed` when the declared Gamma is already
safe and covers the required family, `feasible` when a strict Gamma
restriction is safe and still covers every required configuration, and
`infeasible` when no co-liveness-only restriction can retain declared-product
required coverage.
Only `feasible` sets `installation_required` to true.  A local overpermission
can therefore be diagnosed as infeasible: preventing controllers from being
co-live cannot repair a forbidden choice made by one controller while still
retaining behavior that needs that controller.

Under `exact_projection_through_r`, the output kind is
`co_liveness_projection_only`: it is the greatest safe restriction of the
submitted projection, not a claim about the maxima of the hidden full Gamma.
Installing it means using that restricted projection as a concrete full
co-liveness policy (thereby disallowing unlisted higher-order groups), pruning
any controller declarations that become unreachable, and then resubmitting.
Under `sound_overapprox`, the kind is
`co_liveness_upper_bound_only`, status is `diagnostic_upper_bound`, and
installation is never claimed sufficient.

This object is an offline proposal, not an installed policy.  It always sets
`effect_authorizes` to false and does not alter the submitted manifest,
`deployment.readiness`, `history_admission.structurally_eligible`, or the
verifier's seal kind.  The runtime must install the restriction and submit a
new manifest before it can affect readiness.  `Reject` has no `Admitted`
family and therefore reports `co_liveness_repair: null`.

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
runtime-family refinement, exact evaluation of an attested contract-indexed
projection (`deploymentReady_iff_of_attested_exact_projection`), and reduction
to the older functional partition through a proved canonical adapter.  The
executable `GateClone` subtype still
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
Gate uses that share one controller anchor must agree on origin, version, and
normalized local family.  Thus the executable implements a strict normalization
subclass; unlike the general model-level adapter used by the two-by-two identity
fixture, it does not union disagreeing local families under one anchor.

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

With full `exact` evidence, the model-level check is
`Required <= Raw(Gamma) <= Admitted`.  With `sound_overapprox`, the tool can
establish only `Actual <= RawUpper <= Admitted`; required coverage remains
unproved.  With `exact_projection_through_r`, it directly checks the sandwich
for `Raw(P)` and uses the projection theorem to lift both halves to the hidden
full `Gamma`; `Raw(P)` itself is not an upper bound on `Actual`.  The verifier
cannot establish any adapter attestation or runtime refinement, so it records
those facts as external obligations in every mode.

The seal is conditional on the manifest being a truthful, completely mediated
runtime abstraction.  This artifact does not authenticate receipts or leases,
infer natural-language intent, prove external exactly-once execution, or prove
that an unmodified Claude/Codex runtime realizes the supplied contracts.
