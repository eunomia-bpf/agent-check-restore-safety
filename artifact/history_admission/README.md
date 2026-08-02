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
7. emits a structural certificate or a compact prefix, lineage, forbidden
   union, gate-cut, or gate-clone witness.

Semantic admission and deployment readiness are intentionally separate.
`Inherit` or `ReadmitOK` is structurally eligible only when the independently
verified deployment result is `Ready`.  The verifier emits a
`history_admission` seal, not an effect-authorization credential.  It always
sets `effect_authorizes` to false and lists the runtime obligations that remain,
including manifest authenticity, complete mediation, controller freshness,
atomic redemption, and refinement between the declared controller product and
the runtime's actual behavior.  `NeedsMechanism` and `Reject` remain
diagnostic.

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

## Proof crosswalk and scope

The implementation mirrors the Lean definitions `familyChoice`,
`familyTensor`, `safeFuture`, `StructuralRefinement`, and
`classifyAdmission_sound`.  Minimal nonfaces and coordination components mirror
the exact partition result.  `ControllerCoverAdmission.lean` mechanizes the
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
