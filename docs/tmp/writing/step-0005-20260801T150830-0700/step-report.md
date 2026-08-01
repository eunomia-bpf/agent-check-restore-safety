# Step 0005 report: milestone review and real-trace audit

## Questions and decisions

This WRITING step asked two questions: whether the current manuscript is ready
to pass a CSF 2027 milestone, and whether public real-agent trajectories should
become a new experiment.

The answers are:

1. **Milestone not accepted; major revision.** The one acceptance-blocking
   issue for a theory-led paper is theorem-level novelty separation. General
   configuration structures already express arbitrary permitted families and
   the all-pairs-but-not-the-triple witness; resource/event, consumable-
   authority, and supervisory semantics are closer than the current paper
   makes explicit. The most plausible surviving core is final-owner support iff
   universal owner-group serializability under exact prefix repair and
   immediate cleanup, but that result is neither separated from those
   foundations nor mechanized.
2. **Real trajectories are useful but not required as a broad experiment.** A
   public corpus can establish workload relevance and expose an observability
   gap. It cannot label a history safe or unsafe when trusted lifecycle,
   authority, durable-support, protected-effect, and crash-boundary state are
   absent. Dataset scale cannot replace either the formal theorem or the fixed
   Codex adapter.

This disposition preserves the user's theory-first, high-novelty objective. It
rejects both an easy narrowing to a workspace rollback bug and an unhelpful
pivot to an agent benchmark paper.

## Independent milestone review

The reviewer followed the required serial order: blind full-paper read,
primary-source attack, complete source-grounded reread, and only then an audit
of author intent and retained artifacts. The four reports are:

- `milestone-review-001/01-blind-read.md`;
- `milestone-review-001/02-external-search.md`;
- `milestone-review-001/03-full-reread.md`;
- `milestone-review-001/04-final-verdict.md`.

The review confirms that the problem is real and the principle “authority
follows durable support, not copied state” is strong. It classifies complete
runtime mediation as a major optional strengthening for a clearly theory-led
paper, not as the theory milestone blocker. It independently passed all 24
bounded-model tests and all 33 adapter tests, including the installed Codex
App Server preflight, and found retained counts/hashes consistent. It also
confirmed that the 755-job Lean development covers the finite canonical
lifecycle but explicitly excludes Boundaries I--II.

## Real trajectory result

The complete audit is in
`trace-dataset-scout/trace-dataset-audit.md`. The strongest new public asset is
UW TraceLab v0.0.2, a fixed release of real opt-in Claude Code/Codex telemetry.
The 100,939,722-byte JSONL was downloaded to an ephemeral directory and
verified at SHA-256
`11ce51ec0a25e3d1d95b025bca2f7d1647e47571eb7cc968acd5fc64d4b4fb65`.
A full streaming scan observed:

| Fact | Result |
|---|---:|
| Agent rounds | 665,453 |
| Sessions / deduplicated users | 8,058 / 52 |
| Tool records | 743,819 |
| Tools marked error | 35,453 (4.77%) |
| Sessions with at least one marked tool error | 4,228 |
| Process-continuation records | 75,488 |
| Calls with sanitized command structure | 423,280 |
| Missing / within-session duplicate tool-call IDs | 0 / 0 |

These values show long-lived, failure-prone, orchestration-rich workloads, but
they do not identify semantic Fork/Restore, authority delegation, remote
commit, duplicate effect, or crash-after-effect. The trace audit also checked
SWE-chat, SWE-agent/SWE-bench traces, OpenHands/Orchard, WebArena,
WebArena-Verified, AgentDojo, LangSmith/LangGraph, General AgentBench, Agent LLM
Traces, and StateFork/Waypoint. Different assets expose different components;
none exposes their trusted joint composition.

## Canonical consequences

- `docs/background-related-work.md` now records TraceLab/WebArena evidence,
  StateFork as a native C/R integration target, and the newly decisive
  configuration-structure/resource-semantics novelty threat.
- `docs/evaluation.md` now records the fixed TraceLab scan and the decision not
  to report an unsafe-trace rate or launch a broad dataset benchmark.
- The paper is intentionally unchanged in this step. Adding counts or another
  workload cannot repair the theorem-level acceptance blocker, and changing
  the scientific contract before the separating formal result would be
  premature.

## Routing

Return from final writing to one focused theory loop:

1. construct an explicit encoding of the paper's permitted-family, resource,
   promotion, and cleanup semantics into the closest configuration/resource
   model;
2. prove or refute that final-owner support adds an operational universal-
   serializability theorem not inherited from configuration filtering and
   supervisory enabledness;
3. mechanize Boundary I, exact promotion, and Boundary II with a
   theorem-to-paper coverage map;
4. only after that result, revise the paper and decide whether the adapter
   remains illustrative or the project needs a systems-security pivot.

A later systems experiment may pair StateFork/Waypoint with a protected,
queryable external service and crash litmus histories. It is not the next
highest-information action and is not required merely because real traces were
inspected.
