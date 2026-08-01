# BUILD_AND_EVALUATE Step 0003: Trace Asset Survey

## Question

Do real agent traces add decisive evidence to a theory-heavy authority-
continuity paper, and what is the smallest empirical/runtime study worth doing?

## Result

Yes, but only for workload grounding and observability analysis. Public traces
do not replace the formal theorem and cannot truthfully be labeled for authority
violations because the decisive lifecycle, grant/claim, and external-effect
facts are absent.

The strongest natural corpus is SWE-chat: its published schema joins real
sessions, checkpoints, commits, commands, tool calls, transcripts, and diffs.
General AgentBench and Agent LLM Traces add cross-domain and timing/error
evidence. Microsoft Orchard is a public large controlled corpus with 107,185
SWE trajectories and 3,070 GUI prefixes; one current SWE Viewer row/schema was
inspected, without a bulk download. AgentRx and coding-agent-misalignment
supply failure taxonomies. The Agent Data Protocol is a useful ordinary
correlation-schema baseline.

No available asset contains the complete authority/effect state required by
the theorem. The survey therefore proposes nested observation maps and a
candidate compact, self-contained `HistoryEvent` / `AuthorityEvent` /
`EffectEvent` replay algebra, followed by one dispatch-owning Codex
dynamic-tool adapter. It is not a paper contribution unless independent
witnesses plus an irredundancy, quotient, or lower-bound result go beyond the
existing snapshot corollary.

A read-only six-row pilot of the public Agent LLM Traces Viewer confirms that
ordinary IDs and timestamps are useful but lossy: call/result objects live in
cumulative message JSON, identical call signatures occur under different call
IDs, the current Viewer schema has no `parent_span_id`, and sampled traces have
no independent tool-execution span or trusted effect receipt. This justifies
an aggregate-only full scan; it does not identify unsafe histories.

## Access and evidence boundary

- Primary cards, available schemas, official runtime docs, and representative
  Agent LLM Traces rows were inspected on 2026-08-01.
- The environment is not authenticated to Hugging Face.
- SWE-chat and General AgentBench are gated; no terms were accepted and no
  claim is made that their rows were locally analyzed. Orchard is
  public/ungated at the pinned revision; one row, not the corpus, was inspected.
- No bulk dataset was downloaded and no external state was changed.

## Repository updates

- `docs/background-related-work.md`: asset map, observability candidate, access
  boundary, and novelty effect.
- `docs/evaluation.md`: exact corpus/schema audit and controlled adapter study,
  separating observation ablations from admission-policy baselines.
- `docs/runtime-integration.md`: compact replay schema, trusted-head/sink
  assumptions, adapter-owned Restore/Merge semantics, commands, and oracle.
- `docs/idea-story.md`: H10 records the promising but unproved observability
  extension without changing the current paper thesis.
- Detailed primary-source report: `literature-20260801T122445-0700/report.md`.
- Independent hostile review and five P1 dispositions: `plan-review.md`.
- Reproducible public Viewer pilot, sampled-response hashes, privacy boundary,
  and aggregate-only census decision: `public-trace-pilot.md`.
- Direct Orchard API/card/Viewer status resolution and pinned public revision:
  `orchard-access-check.md`.

## Independent review outcome

The plan required several hostile revisions: theorem
tautology/non-distinctness, incomplete replay/durability assumptions, mixed
comparison axes, an ill-typed replay target, ambiguous observation keys, and a
non-executable adapter matrix. A direct final source check also superseded an
intermediate stale interpretation of Orchard availability. The revision
resolves the planning defects without pretending the theorem or adapter result
already exists. Two independent final audits returned **accept** with no P0/P1
blocker. The surviving observability idea remains a gated candidate, not part
of the current paper thesis.

## Decision

Do not turn the paper into a broad prompt benchmark. First define `O0`--`O2`,
prove independent topology/authority/effect witnesses, and seek componentwise
necessity plus replay sufficiency. Then run a reproducible schema/workload
study and the fixed 20 deterministic instrumented histories. If the result
collapses to the existing snapshot corollary or tautological state logging,
retain traces only as motivation and workload selection.
