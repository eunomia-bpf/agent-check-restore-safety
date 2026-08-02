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
   `Required <= Physical <= Admitted`, distinguishing exact realization from a
   safe restriction that omits only optional behavior; and
7. emits a structural certificate or a compact prefix, lineage, forbidden
   union, gate-cut, or gate-clone witness.

Semantic admission and deployment readiness are intentionally separate.
`Inherit` or `ReadmitOK` is structurally eligible only when the independently
verified deployment result is `Ready`.  The verifier emits a
`history_admission` seal, not an effect-authorization credential.  It always
sets `effect_authorizes` to false and lists the runtime obligations that remain,
including manifest authenticity, complete mediation, controller freshness,
and atomic redemption.  `NeedsMechanism` and `Reject` remain diagnostic.

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
the exact partition result.  The access-relation controller check is a finite
executable extension used to expose cloned-gate product expansion; it is not
yet a mechanized generalization of the partition theorem.

Cell identity, lineage/lease transport, and controller identity are three
separate checks.  An alias requires the same stable cell anchor, authority atom,
commitment key, and effect-binding digest; conflicting parent or lease claims
do not invalidate that identity proof, but disable structural inheritance and
force readmission or revalidation.  Conversely, two gate uses may reach the
same aliased cell while still naming distinct controller anchors.

The physical-family calculation treats controller anchors declared co-live as
independently product-composable.  A runtime with a hidden shared ratifier must
represent it as one authoritative controller or supply a stronger joint
contract; co-liveness alone is not an exploit proof.  `GateClone` and `GateCut`
are precise witnesses under this independent-product abstraction.

The seal is conditional on the manifest being a truthful, completely mediated
runtime abstraction.  This artifact does not authenticate receipts or leases,
infer natural-language intent, prove external exactly-once execution, or prove
that an unmodified Claude/Codex runtime realizes the supplied contracts.
