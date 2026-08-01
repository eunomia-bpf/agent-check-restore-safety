# Plan Review: RQ3 Canonical Topology Closure

**Reviewer role:** fresh read-only independent plan reviewer
**Initial verdict:** revise before preflight

The reviewer judged the experiment coherent and paper-valuable but found four blocking ways in which a green run could fail to repair the previous mixed verdict.

1. A single atomized `checkTopology` could merely Booleanize the old fieldwise `TopologyShape`. Canonical Fork/Restore must derive target structure and load simulation from exact builders, source invariants, and checked fiber conservation; only arbitrary Merge may enumerate target structure.
2. New topology-only step and trace relations could coexist with the old authoritative `Step.topology` and `Step.directMerge`. The run must instead remove those entry points or replace the authoritative full lifecycle, and the final trace theorem must cover all existing non-topology rules plus the new operations.
3. Preservation alone permits a degenerate builder that drops every useful future. Exact membership theorems must distinguish choice, parallel, replace, and live semantics and preserve unrelated pulled-back guarded context.
4. Simulation Merge and direct-admission Merge need distinct checkers, theorems, constructors, and witnesses; only direct admission may invoke `checkAC target`.

The reviewer also required exact fragment-domain/provenance/conservation semantics, active/open branch exactness or an explicit weaker scope, actual use of fiber conservation in canonical load proofs, exact restriction epoch behavior, a fresh-fragment preflight, and additional negative controls for mixed fibers, invalid `rho`, degenerate shapes, history mutation, and Merge-mode separation.

The revised plan accepts all P0 findings. It freezes exact canonical membership semantics, source-derived canonical structure and simulation, a separate arbitrary-Merge structure checker, two Merge modes, active-branch exactness, and replacement of the old authoritative topology constructors. It narrows the fragment claim to preallocated-unissued finite IDs because compatible refined bindings and issuer approval are not represented in the Lean state. The frozen witnesses and preflight were strengthened accordingly.

## Follow-up

The same reviewer approved the revised plan for real preflight. The reviewer confirmed that canonical and arbitrary-Merge checking are now separated, exact shape rules exclude degenerate restrictions, fiber conservation is load-bearing, the old topology entry points must leave the authoritative full lifecycle, active-branch exactness is explicit, and simulation/direct Merge have distinct premises and controls. One implementation guard remains: the canonical owner/projection relation must be derived from the builder and `checkTransfer_sound`, never accepted as an additional logical certificate.

During implementation, that guard exposed one concrete source-local obligation: the singleton projection atom alone permits a retired parent to remain a target claim owner, even though the computed target support excludes it. The canonical checker therefore also checks that every proposed target owner belongs to the builder-computed active set. This is operation-input validation, not target-WF enumeration; it is used directly to derive target support and open-owner facts.
