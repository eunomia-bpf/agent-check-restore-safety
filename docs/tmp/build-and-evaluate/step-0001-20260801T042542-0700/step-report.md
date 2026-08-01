# BUILD_AND_EVALUATE Step 0001

## Recovery state

- Active phase: `BUILD_AND_EVALUATE`.
- Selected paper question: RQ3, abstract lifecycle preservation and conditional trace authority safety.
- Scientific contract: unchanged. Boundary I/II remain separate paper proofs; a real dispatch-owning Claude/Codex adapter remains future RQ3/RQ4 evidence.
- User instructions: recovered from `docs/user-instruction.md`; Messages 11--13 were added verbatim after a log-completeness audit.

## EXPERIMENT gate

- Admission and frozen theorem matrix: `experiment-001/plan.md`.
- Independent plan review and follow-up approval: `experiment-001/plan-review.md`.
- Real preflight: Lean 4.30.0 and Mathlib 4.30.0 are pinned; the final Lake package and fresh `leanchecker` replay passed.
- Raw preflight evidence: `lean/results/preflight.log` and `lean/results/leanchecker-preflight.log`.

## Full-run evidence

- The finite model/checker, lifecycle semantics, and conditional trace/effect theorem are implemented in 1,850 lines across five Lean model/proof modules, plus a 60-line audit module (2,021 lines including the README).
- All ten frozen paper-facing theorem names are exported through `AuthorityContinuity.Main`. Audited auxiliary results cover terminal-ID monotonicity, epoch monotonicity, durable-before-attempt, and preservation of stable operation bindings.
- A clean build after `lake clean` and restoration of the pinned Mathlib cache completed all 742 jobs in 13.46 seconds with maximum resident set size 2,109,000 KiB. Raw output is in `lean/results/build.log`.
- The placeholder/project-declaration scan found no `sorryAx`, `sorry`, `admit`, project `axiom`, or project `constant`. `#print axioms` reports only the approved Lean foundations `propext`, `Quot.sound`, and `Classical.choice`; raw statements and dependencies are in `lean/results/axioms.log`.
- An independent `leanchecker --fresh AuthorityContinuity.Main` replay exited zero in 136.89 seconds; `lean/results/kernel-replay.log` records the otherwise silent successful invocation.
- The implementation README explicitly limits the topology result to a generic identity-preserving conditional certificate. Canonical Fork/Restore shape predicates, `Mono_0(pi)`, transfer-map fiber conservation, fragmentation/fresh issuance, Boundary I/II, and a real dispatch-owning runtime refinement are not mechanized by this experiment.

The technical full run is complete. A fresh read-only result reviewer independently inspected the statements and replayed the kernel, then returned a **mixed** scientific verdict. The computed restriction, exact Prepare/cleanup, ticket, binding, AC-simulation, and conditional trace obligations are real machine-checked results. However, the generic topology certificate carries the target's main structural WF fields explicitly, and the development does not derive them from the paper's canonical Fork/Restore/Merge shapes or a checked transfer-map implementation. Complete mediation and per-ID aggregate outcomes also remain refinement hypotheses. The full assessment is `experiment-001/result-review.md`.

## Next gate

The mixed-result rule applies: retain the development and raw audit evidence, but do not add a mechanization claim to the paper. The next paper-value experiment must replace the generic topology-WF interface with computed canonical Fork/Restore/Merge targets and a checked projection/transfer certificate, or keep the Lean work explicitly internal. A separate dispatch-owning adapter remains necessary for the concrete-runtime part of RQ3/RQ4.
