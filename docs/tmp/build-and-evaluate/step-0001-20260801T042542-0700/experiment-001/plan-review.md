# Plan Review: RQ3 Mechanized Lifecycle Core

**Review timestamp:** 2026-08-01T04:32:00-07:00

**Reviewer role:** fresh read-only plan reviewer
**Initial verdict:** revise before preflight

The reviewer found the experiment paper-valuable and executable with Lean 4, Lake, `#print axioms`, and `leanchecker`, but identified three validity blockers:

1. Boundary I and Boundary II answer RQ1/RQ2 and cannot be conjunctive success requirements for the selected RQ3 experiment. Only lifecycle-preservation dependencies belong here; a positive result must be scoped to abstract preservation and conditional trace refinement, not a real Claude/Codex refinement.
2. Reserve and direct-admission Merge deliberately check target solvency, whereas simulation topology changes, exact Prepare/cleanup, restriction/revocation, ticket steps, and trace induction must derive it. The plan must distinguish these cases and state whether the finite checker itself is proved sound.
3. The plan needs a frozen list of paper-facing constants, a root module importing them all, an exact clean-build/kernel-replay command, failure on `sorryAx` and undeclared project axioms, and an explicit policy for Lean foundational axioms.

The revised plan accepts all three findings. It reclassifies the experiment as supporting RQ3 evidence, removes Boundary I/II from its success condition, distinguishes checked-target from derived cases, requires `checkAC_sound`, freezes ten paper-facing constants with their assumptions and conclusions, and makes the root import, clean build, axiom scan, and kernel replay explicit.

## Follow-up

The follow-up confirmed that all three scientific blockers were closed and found one command-level defect: `leanchecker` takes a module name rather than an `.olean` path. The plan now uses `lake env leanchecker --fresh AuthorityContinuity.Main`. With that correction, the reviewer approved the plan for real preflight.

During preflight, `lake clean` correctly removed local build products, including cached dependency outputs, so an unqualified `import Mathlib` began rebuilding the whole library. This is a dependency-path deviation, not a theorem change: the root now imports only required modules, and the clean workflow restores the pinned official Mathlib cache before building the project target.

## Pre-proof model clarification

The first lifecycle interface pass exposed two representation obligations before any preservation proof was attempted. First, terminal non-reuse needs an explicit `unissued` claim status (equivalently, a monotone issued-ID set); otherwise fresh Reserve would be indistinguishable from reviving a terminal ID. Second, `checkAC` discharges only the quantitative target-AC obligation for Reserve/direct-admission Merge. Their target well-formedness must be derived from constructor-local freshness, epoch, binding, support, and partition evidence, not assumed as `WF target`. The frozen `step_preserves_wf_ac` row now says this explicitly. This is a strengthening/clarification of the premises already present in the paper rules, not a theorem weakening or an added target-invariant premise.
