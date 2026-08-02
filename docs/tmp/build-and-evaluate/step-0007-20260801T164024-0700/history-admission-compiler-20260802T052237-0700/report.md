# History-admission compiler milestone

Date: 2026-08-02

## Outcome

Implemented a dependency-free, offline history-admission artifact under
`artifact/history_admission/`.  It is not an agent runtime or checkpoint
engine.  An untrusted compiler derives finite witnesses from a typed
Fork/Restore/Merge manifest; an independent bit-mask verifier reconstructs the
complete result without importing the compiler.

The theory determines the interface:

- target handles are arm-tagged and quotiented only by explicit semantic-cell
  evidence;
- cell identity requires one stable anchor, authority atom, commitment key,
  and effect-binding digest;
- parent/lease transport and controller identity remain separate from the
  cell quotient;
- choice and tensor generate the candidate and required future families for
  all six typed operators;
- the durable receipt prefix derives the greatest safe subfamily;
- the four semantic outcomes are `Inherit`, `ReadmitOK`, `NeedsMechanism`, and
  pruning-only `Reject`;
- controller co-liveness derives a physical future family under an explicit
  independent-product abstraction; and
- deployment is accepted exactly when
  `Required <= Physical <= Admitted`.  Equality is reported separately as
  exact fidelity, while a strict safe restriction may omit optional behavior.

The artifact exposes prefix replay, lineage collision, forbidden union,
GateClone, GateCut, controller over-permission, and missing-required-behavior
witnesses.  Minimal nonfaces expose higher-order constraints such as `U(2,3)`,
where every pair is allowed but the triple is forbidden.

## Trust-boundary correction

The verifier emits a `history_admission` structural seal, not an effect
authorization.  `effect_authorizes` is always false.  A runtime must still
discharge manifest/ledger/receipt authenticity, complete mediation,
controller installation and freshness, atomic redemption, fresh issuance for
readmission, and lease revalidation where applicable.  This prevents the
artifact from silently claiming lease authentication, external exactly-once
execution, or a real Claude/Codex refinement that the model does not prove.

Likewise, `GateClone` and `GateCut` are precise under the manifest's
independent-controller product abstraction.  A hidden shared ratifier must be
represented as one authoritative controller or by a future joint-contract
extension.

## Hostile-review fixes incorporated

1. Replaced physical-family equality as the readiness test with
   `Required <= Physical <= Admitted` and retained equality as an exact-fidelity
   grade.
2. Rejected declared controllers omitted from controller-future support.
3. Preserved and reported `exact` versus `sound_overapprox` arm coverage.
4. Separated semantic-cell aliasing from parent and lease transport.
5. Added effect-binding digests to the alias identity check.
6. Renamed the verifier output from effect authorization to structural history
   admission and made external obligations explicit.
7. Added raw list, string, occurrence, gate-use, state-expansion, and controller
   product caps.
8. Added the aliased-cell/cloned-controller boundary test: one semantic cell is
   authority-safe only conditionally on an external atomic-redemption layer.

## Validation

Commands and results:

```text
cd artifact
python3 -m unittest -v test_history_admission
28 tests passed

python3 -m unittest -v
53 tests passed in 2.233 seconds

python3 explore.py
all schema-v5 finite authority-continuity checks passed
```

The tool-specific suite includes:

- parity tests for all six typed operators;
- all four semantic outcomes;
- exact, safe-restriction, unsafe-overapprox, missing-required, and mixed
  controller realizations;
- cell alias versus gate identity separation;
- GateClone and GateCut witnesses;
- the three-cell higher-order minimal-nonface witness;
- receipt monotonicity, binding stability, strict JSON, tamper, and resource-cap
  failures;
- compiler determinism and verifier independence; and
- an exhaustive oracle over all 19 downward-closed families on three cells.
  Across every full-support candidate, every required subfamily, and every
  physical family, 2,166 cases agreed with the refinement relation and were
  independently accepted by the verifier.

CLI smoke passed for compiler followed by verifier.  The resulting seal was:

```json
{
  "effect_authorizes": false,
  "seal_kind": "history_admission",
  "structurally_admits": true,
  "valid": true
}
```

The updated anonymous supplemental command produced exactly the twelve files
listed in `artifact/README.md`, excluding repository history, caches, private
traces, and research notes.

## Remaining theorem boundary

The Lean development already proves the functional-partition exact
factorization theorem and the typed semantic admission classifier.  The
executable controller-cover relation permits one semantic cell to be reachable
through multiple controller instances.  Its generalized theorem—especially
`Required <= Physical <= SafeFuture`, minimal product witnesses, and repair
synthesis—is not yet mechanized.  It should be the next theory step rather than
being implied by this finite implementation.
