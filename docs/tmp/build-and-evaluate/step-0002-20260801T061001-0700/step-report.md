# BUILD_AND_EVALUATE Step 0002

## Selected uncertainty

This step revisited the precise blocker from Step 0001: whether the paper's
choice/parallel Fork, replacing/live Restore, fragment-conserving transfer,
and two Merge modes can form a closed machine-checked lifecycle without
smuggling target well-formedness or authority continuity into a logical
certificate.

The admitted plan and its independent revision are in
`experiment-001/plan.md` and `experiment-001/plan-review.md`.

## Implemented result

- Canonical Fork/Restore descriptors now compute exact target contracts,
  active branch epochs, and projections.
- The transfer checker validates exact domain, retained-or-preallocated-fresh
  provenance, no mixed retained/fresh fiber, typed grant agreement, owner
  projection, and coordinatewise fiber conservation.
- Canonical target `LWF`, `AC`, and `ActiveExact` are derived from source
  invariants plus the checked local inputs; the AC proof uses the fiber theorem
  and never checks target AC.
- Explicit simulation Merge and direct-admission Merge use distinct checkers
  and theorems; only the direct mode checks target AC.
- One authoritative `Step` and trace closure cover all prior lifecycle rules,
  four canonical transformations, and both Merge modes, preserving terminal
  IDs, epochs, tickets, receipts, stable bindings, and authority continuity.
- Named executable controls accept all intended forms and reject demand
  copying, mixed fibers, terminal reuse, invalid transfer sources, closed epoch
  reuse, unsafe co-durability, and degenerate choice behavior.

## Validation

- Targeted preflight: 750 jobs, 1.60 seconds, 2,059,840 KiB maximum RSS;
  `fresh_fragment_parallel_preflight` depends only on `propext`,
  `Classical.choice`, and `Quot.sound`.
- Final clean build: 755 jobs, 10.02 seconds, 2,099,376 KiB maximum RSS.
- Final audit and fresh kernel replay: exit zero in 88.25 seconds, 2,045,236
  KiB maximum RSS.
- Raw evidence: `lean/results/topology-preflight.log`,
  `lean/results/topology-build.log`, `lean/results/topology-axioms.log`, and the
  retained compatibility copy `lean/results/axioms.log`.
- Independent result review: **positive**.  The complete assessment and
  paper-safe scope are in `experiment-001/result-review.md`.

## Interpretation

Step 0001's mixed result is superseded for the finite abstract-topology claim.
The paper may report the canonical lifecycle theorem as Lean-mechanized.
The result remains deliberately narrower than a deployed runtime theorem:
fragment IDs are preallocated and unissued, arbitrary Merge checks finite
structure atoms, and complete mediation, effect-binding truth, aggregate sink
outcomes, Boundary I/II, and a concrete Claude/Codex adapter remain open.

## Next evidence gate

Use real trajectories to characterize the workload and the observability gap,
then build one dispatch-owning adapter (Codex App Server dynamic tools is the
leading path) with fixed crash/fork/resume litmus histories.  Public traces can
validate which operations and failures occur, but cannot establish the missing
authority/effect lineage or replace the formal theorem.
