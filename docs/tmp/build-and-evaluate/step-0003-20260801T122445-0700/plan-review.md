# Independent Plan Review: Trace Asset Survey

## Verdict

The initial review was **revise** with five P1 defects. A second audit found the
first, second, third, and fifth defects repaired, the fourth only partly
repaired, and three remaining/new P1 defects. After the listed dispositions,
two independent final audits returned **accept**, with no remaining or newly
introduced P0/P1 defect. No review found a P0 defect.

## Findings and dispositions

1. **P1 — The observability theorem was not distinct or nontrivial.** The
   replacing/live witness reused the existing snapshot corollary, while
   recording all checker state would make sufficiency tautological.
   **Resolved:** `docs/background-related-work.md` and `docs/idea-story.md` now
   require nested observation equivalences, independent topology/effect
   witnesses, componentwise necessity or an information lower bound, and
   replay reconstruction. The candidate is demoted to motivation unless it
   yields an irredundant event basis, observation quotient, or comparable
   monitorability boundary.

2. **P1 — The enriched trace did not establish sufficiency.** Opaque
   `projection_id`/`support_ref` fields were not replayable, a hash chain had no
   non-rollbackable head, and remote-success-before-commit remained ambiguous.
   **Resolved:** `docs/runtime-integration.md` now requires canonical
   self-contained certificate bodies, authenticated hashes, a crash-atomic log
   with an independently anchored durable head, write-ahead ordering, and an
   authenticated idempotent/queryable sink. These are explicit refinement
   assumptions, not empirical conclusions.

3. **P1 — Comparison axes conflicted.** Information ablations and admission
   policies were mixed and named inconsistently.
   **Resolved:** `docs/evaluation.md`, `docs/runtime-integration.md`, and the
   detailed report now separate `O0`--`O2` observation ablations from
   `P0`--`P3` admission policies and state a decision rule for each policy.

4. **P1 — The adapter experiment was not executable as a plan.** App Server
   did not natively provide every Restore/Merge meaning; the plan lacked fixed
   cells, commands, versions, raw paths, completion rules, and an independent
   oracle.
   **Resolved:** `docs/runtime-integration.md` makes Fork topology,
   replace/live Restore, and Merge adapter-owned semantics; fixes a 20-history
   suite; defines crash points, mock-sink state, L1/L8/L10/L13 and sink oracles;
   and specifies planned commands, lock manifests, raw/summary paths, and exit
   criteria. The scope is prototype refinement over Codex histories, not a
   claim of native Codex semantic coverage.

5. **Source-status dispute — Orchard availability.** An intermediate source
   review reported a paused release and caused the first revision to demote
   Orchard. A later direct API/card/Viewer check superseded that finding:
   revision `70c05ec1f20f823ae6adc60374922e9271bb74e2` is public/ungated, exposes
   SWE/GUI configs and Viewer rows, and ships 107,185 SWE plus 3,070 GUI rows.
   **Final disposition:** Orchard is a public controlled fallback; one SWE row
   was inspected, no bulk corpus was downloaded, and the revision is pinned.

## Second-audit findings and dispositions

1. **P1 — The replay target was ill-typed.** `SimulatedTrace` is an execution
   relation, not an abstract state. **Resolved:** the plan now reconstructs the
   genesis `LifecycleState`, every abstract label and successor, and each
   checker decision, then asks whether the corresponding concrete edges form a
   `SimulatedTrace`.

2. **P1 — Completion contradicted the experiment's purpose.** `O0`/`O1` were
   expected to be insufficient and `P0`--`P2` were expected to disagree with
   the oracle, yet all were required to return the oracle decision.
   **Resolved:** observations are scored by mixed-label fibers, abstentions,
   and decoder error; only `O2` must replay exactly. Baseline policy
   false accepts/rejects are results; only `P3` must match the fixed suite.

3. **P1 — The 20-history matrix and policy transitions were underspecified.**
   L8 had no dispatch to receive a crash, L1/L10 had ambiguous injection sites,
   and split allocation plus Restore/Merge/retry/revoke/ticket behavior was
   missing. **Resolved:** `docs/runtime-integration.md` now enumerates
   C01--C20, applies crash modes only to named effect sites, defines the shared
   sink/crash protocol, and gives complete fixed-suite transition rules for
   `P0`--`P3`. An earlier baseline rejection is recorded rather than
   fabricating an unreachable state.

## Final-audit findings and dispositions

1. **P1 — Observation equivalence ignored the next action and raw IDs made
   `O1` fibers singleton.** **Resolved:** the executable key is now
   `(alpha(O_i(prefix)), normalize(next_action))`. Alpha-renaming preserves ID
   alias structure/order while removing run-local spellings and absolute time;
   the normalized request fixes operation, source role, demand, binding, and
   same/fresh relation. C13/C14, C16/C18, and C02/C03 are the explicit
   topology, authority, and effect witness pairs.

2. **P1 — Case ranges and effect outcomes were not executable.** “C01--C04,
   all modes” did not bind case IDs to fault sites, and “at most once” allowed
   a degenerate implementation that never completed the effect. **Resolved:**
   C01--C12 now each name one crash mode and require an exact terminal sink
   outcome/receipt or exact zero-at-crash followed by recovery; C13--C20 remain
   individually specified topology cases.

3. **P1 — Orchard status in the first revision was stale.** **Resolved:** the
   direct official API/card/Viewer verification above is authoritative for
   this step and all documents now use the pinned public revision.

## Post-revision assessment

**Accept as an evidence roadmap.** The revision still does not establish a new
observability theorem, complete mediation, production Codex refinement, or
exactly-once behavior for arbitrary sinks. Those remain explicit future proof
and prototype gates.
