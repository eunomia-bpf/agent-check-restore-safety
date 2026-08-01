# Independent Result Review: RQ3 Canonical Topology Closure

**Review status:** positive

**Reviewer role:** fresh, read-only result reviewer
**Technical basis:** complete statement/call-chain inspection of the frozen Lean
modules, source and axiom audit, the recorded clean build, and fresh kernel
replay; no scientific files were modified by the reviewer

## Run status

The run satisfies the positive interpretation frozen in the approved plan.
Canonical Fork/Restore targets are computed from the source state, operation,
and checked transfer rather than supplied as an arbitrary target.  Their
structural well-formedness, active-support exactness, load simulation, and
authority continuity are derived from the builders and source invariants.
The authoritative full lifecycle contains the old non-topology rules, all four
canonical forms, and separately admitted simulation and direct Merge modes.

A clean build completed 755 jobs in 10.02 seconds with maximum resident set
size 2,099,376 KiB.  The source audit found no proof placeholder, project axiom
or constant, or occurrence of the retired `TopologyShape` interface.  Printed
dependencies are restricted to `propext`, `Quot.sound`, and
`Classical.choice`; `leanchecker --fresh AuthorityContinuity.Main` succeeded.

## Load-bearing evidence

- `Topology.lean:138` and `Topology.lean:478` define the exact operation data
  and computed target.  No canonical theorem accepts an arbitrary successor.
- `Topology.lean:423--467` limits `checkCanonical` to operation freshness,
  source-local transfer, and ownership in the builder's computed active set.
  It does not decide target `WF`, `LWF`, `AC`, or per-configuration simulation.
- `Topology.lean:497--637` derives target core WF, `ActiveExact`, lifecycle WF,
  and AC.  The quantitative proof calls
  `Transfer.topology_fiber_conservation` at `Topology.lean:621`; all four
  operation wrappers share that proof.
- `Transfer.lean:61--133` and `Transfer.lean:180--296` check and prove exact
  target domain, tentative-source provenance, retained-versus-fresh fiber
  separation, typed grant agreement, owner projection, and coordinatewise
  fiber conservation.  Fresh fragments are source-`unissued` identifiers.
- `Topology.lean:371--421` gives distinct exact membership theorems for choice
  Fork, parallel Fork, replacing Restore, and live Restore.  Freshness and
  cardinality premises exclude degenerate child reuse.
- `Merge.lean:216--250` visibly separates simulation admission from direct
  admission.  Simulation checks structure, `Mono_0`, and the load simulation;
  direct admission has no projection and is the only Merge mode that invokes
  target `checkAC`.
- `Step.lean:30--63` is the sole paper-facing step relation.  It covers every
  `CoreStep`, the computed canonical target, simulation Merge, and direct
  Merge.  `Trace.lean:26--51` closes over that full relation and preserves
  `LWF`, `AC`, and `ActiveExact`.
- `TopologyExamples.lean` contains named accepting and rejecting controls for
  all four canonical operations, fresh fragmentation, copied demand, mixed
  fibers, terminal-ID reuse, invalid `rho`, closed-epoch reopening, Merge-mode
  separation, unsafe co-durability, history preservation, and replacing
  Restore.  `fresh_fragment_parallel_preflight` reaches the final preservation
  theorem and has only the whitelisted foundational dependencies.

## Frozen-matrix assessment

| Obligation | Assessment |
|---|---|
| Exact restriction epoch behavior | Pass. Unissued and closed identities remain in their class; only excluded open identities close. |
| Exact four canonical contracts | Pass. Distinct membership theorems preserve unrelated context through the canonical preimage. |
| Checked fragment transfer | Pass. Exact domain, provenance, no mixed retained/fresh fiber, grant agreement, and coordinatewise conservation are executable and sound. |
| Canonical `LWF`/`AC` | Pass. Derived from source invariants and checked local data; no target-invariant premise or target AC recheck. |
| Simulation/direct Merge separation | Pass. Distinct descriptors, checkers, constructors, theorems, and separating witnesses. |
| Full Step/Trace closure | Pass. The old non-topology lifecycle and every new topology mode share one preservation theorem. |
| History properties | Pass. Terminal IDs, branch/grant epochs, tickets, receipts, and stable operation bindings are preserved as specified. |
| Source/kernel audit | Pass. No placeholder/project axiom; only the documented Lean foundations; fresh kernel replay succeeds. |

## Scope limits

- Fragmentation covers a fixed finite identifier type with identifiers that
  already exist and are `unissued` in the source.  Dynamic identifier-space
  extension, issuer approval, and refined effect-binding validity are not
  mechanized.
- Arbitrary Merge uses atomized finite structure checks.  It is not derived by
  the canonical Fork/Restore builder.  Simulation Merge checks `Mono_0` as an
  admission condition, although the stronger per-configuration inequality is
  what discharges AC.
- `ActiveExact` is an explicit source invariant and is preserved by every
  authoritative step.
- Boundary I, Boundary II, general pseudo-Boolean checker completeness,
  natural-language binding, complete mediation, aggregate sink truthfulness,
  and a deployed Claude/Codex refinement remain outside this result.

## Paper decision

The paper may now report a finite abstract-lifecycle mechanization with exact
scope.  Paper-safe wording is:

> For the finite preallocated-ID model, Lean kernel-checks that the four
> computed canonical Fork/Restore transformations preserve lifecycle
> well-formedness, authority continuity, and exact active support from source
> invariants plus executable source-local checks. Explicit Merge is covered by
> separately checked simulation and direct-admission modes. This is
> mechanized abstract-topology evidence, not an end-to-end refinement proof
> for a production agent runtime.

The review initially identified two release-hygiene issues: anonymous controls
and missing topology-specific logs.  Before finalization, every control was
named and frozen in `scripts/audit.sh`, and the planned preflight, clean-build,
and axiom logs were retained under `lean/results/`.  Neither issue affected the
scientific verdict.
