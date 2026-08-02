# Exact coordination decomposition: mechanization report

**Date:** 2026-08-02

## Question

Given a finite downward-closed family of semantic cells that may become
durable together, which cells must remain behind the same authoritative
controller if a runtime wants independently runnable blocks to preserve the
family exactly?

This is a supporting theorem for the proposed compiler.  Simplicial-complex
minimal nonfaces, hypergraph components, and relation factorization are
classical; the result is not presented as new combinatorics.

## Model

- `source : Finset (Finset U)` is nonempty, contains the empty configuration,
  and is downward closed.
- `blockOf : U -> B` proposes a controller block for every semantic cell.
- `localProduct source blockOf` is the maximal asynchronous recombination for
  which every block restriction is source-admissible.
- `MinimalNonface source K` says that `K` is forbidden but every proper subset
  is admitted.
- `DirectlyCoupled source u v` holds when `u` and `v` occur in one minimal
  nonface.
- `MustCoordinate` is the equivalence closure of `DirectlyCoupled`.

The `localProduct` interpretation deliberately makes the operational premise
visible.  A concrete runtime must prove that its independent controllers can
jointly realize the relevant local choices.  Without that refinement, a cut
minimal nonface proves failure of policy-oblivious certificate inheritance,
not necessarily a reachable exploit.

## Checked results

1. Every forbidden set on the finite support contains a minimal nonface.
2. If a block labelling cuts a minimal nonface `K`, then `K` is admitted by the
   local product but forbidden by the source.
3. A block labelling factorizes the source exactly iff every minimal nonface is
   contained in one block.
4. Equivalently, exact factorization holds iff the labelling is constant on
   `MustCoordinate`.
5. `MustCoordinate` is the least equivalence relation containing the direct
   co-location requirements. Its classes therefore induce the finest exact
   block partition, unique up to block-label renaming.
6. Every cut minimal nonface yields an explicit natural-number additive policy:
   the source is safe at capacity `|K|-1`, while the independently recombined
   target is unsafe.

The sixth result reuses the already checked configuration-morphism bridge; it
connects a factorization failure to an actual authority-policy witness rather
than only unequal set families.

## Higher-order control

The `U_{2,3}` fixture permits every subset of three cells of size at most two.
Thus every pair is allowed, but the triple is a minimal nonface.  Splitting one
cell from the other two causes independent local checks to admit the forbidden
triple and produces the additive capacity-two counterexample.  This rules out
a pairwise conflict graph as a complete coordination analysis.

## Validation

Commands:

```text
lake env lean AuthorityContinuity/CoordinationDecomposition.lean
lake build AuthorityContinuity.CoordinationDecomposition AuthorityContinuity.Main
lake env lean AuthorityContinuity/Audit.lean
lake env leanchecker --fresh AuthorityContinuity.Main
```

All passed, including the independent fresh kernel replay.  The integrated
build completed all 8,500 jobs.  The theorem audit
reports only Mathlib's admitted foundations `propext`, `Classical.choice`, and
`Quot.sound`; no project axiom, `sorry`, or `admit` is used.  An independent
hostile review found no circular target-safety premise and approved the theorem
proofs after two documentation clarifications: relation order versus partition
order, and the joint-reachability scope of `localProduct`.

## What this does and does not establish

Established:

- the exact coordination requirement for a fixed future-configuration family;
- a mechanically auditable certificate criterion;
- a compact counterexample suitable for a compiler diagnostic;
- a multiway constraint that pairwise analyses miss.

Not established yet:

- that a concrete Claude/Codex runtime realizes the maximal local product;
- the typed Fork/Restore/Merge rule that constructs the candidate target family;
- cell alias/reissue synthesis for lineage collisions;
- durable receipt and refinement-certified lease transport;
- executable union-find/code generation.

## Next step

Define one typed history-transformation request that carries source/target
contracts, cell lineage, outstanding lease bindings, and durable receipt
prefix.  Its structural judgment will compose three independent certificates:
exact gate factorization, locally injective cell transport, and monotone
commitment preservation.  Only then should the Python tool lower the semantic
answer into `Copy/Share/Split/Persist/Revalidate/Reject` actions.
