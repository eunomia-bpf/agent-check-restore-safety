# Literature and Asset Report: Real Agent Trajectories

## Objective

Determine whether real agent trajectory datasets materially strengthen the
authority-continuity paper, which assets are usable, what claims they can and
cannot support, and what compact instrumented trace is worth testing for the
concrete runtime refinement.

This is a claim-oriented asset survey. It does not report a completed corpus
analysis or alter the current paper's headline theorem.

## Candidate claims under test

1. **Workload claim:** history-transforming and outward-effect-like operations
   occur in real tool-using agent sessions often enough to justify the model.
2. **Schema claim:** ordinary agent traces correlate messages and tool calls but
   omit security-critical authority/effect state.
3. **Formal observability claim:** two concrete histories can have the same
   ordinary trace observation yet require different safe next admission
   decisions.
4. **Replay claim:** a compact trusted lifecycle, grant/claim-lineage,
   stable-effect-phase, and receipt event algebra reconstructs the abstract
   checker state under explicit mediation, durability, certificate, and sink
   assumptions.

Only Claim 2 receives source-grounded support from this survey. Claim 1 needs a
real corpus run; Claims 3--4 need proofs and controlled runtime evidence.

## Search and verification log

Primary queries and inspections included:

- real coding agent trajectories checkpoint commit session Claude Code Codex;
- public tool-call trajectory dataset errors retries OpenTelemetry;
- agent failure trajectory taxonomy real developer sessions;
- standardized agent trace format tool call observation IDs;
- official Codex App Server fork lineage dynamic tool call schema;
- official Claude Code checkpoint Bash subagent external-change limitations;
- Hugging Face Dataset Viewer schemas and representative rows for public Agent
  LLM Traces and Orchard SWE.

All factual entries below were verified against the primary dataset card,
official repository/documentation, or paper page on 2026-08-01. The environment
is not authenticated to Hugging Face. No gated terms were accepted and no bulk
corpus was downloaded.

## Source families and verified assets

### A. In-the-wild developer trajectories

**SWE-chat**

- Primary sources: [dataset card](https://huggingface.co/datasets/SALT-NLP/SWE-chat)
  and [paper](https://arxiv.org/abs/2604.20779).
- Verified scope: 205 repositories, 5,851 sessions, 5,851 raw transcripts,
  2,692,480 conversation/metadata entries, 13,406 checkpoints, and 14,459
  commits. Supported agents include Claude Code, Codex, Gemini CLI, Cursor,
  OpenCode, and GitHub Copilot CLI.
- Useful fields: stable session/checkpoint/commit/turn keys; branch; timestamps;
  tool names/call IDs/input; extracted shell commands; system events; file
  snapshots; checkpoint-to-commit joins; full diffs and files touched.
- Scientific use: primary natural workload census and source of minimal real
  examples.
- Limits: a checkpoint row identifies a save point, not necessarily Restore;
  fork/restore/merge/approval are not a uniform typed lifecycle relation;
  external resources have no before/after snapshot; no grant, claim, effect
  phase, or durable-support contract is present.
- Access: ODC-BY but gated behind sharing contact information. No local access
  is currently authorized.

**Coding-agent-misalignment**

- Primary source: [replication repository](https://github.com/ND-SaNDwichLAB/coding-agent-misalignment).
- Verified scope: replication package for a study of 20,574 real-world coding
  sessions.
- Scientific use: motivation and damaging-history taxonomy, such as unwanted
  file/history/publish behavior; not a substitute for typed lifecycle traces.
- Limits: the public replication structure and labels do not provide a single
  interoperable authority/effect execution trace for this theorem.

### B. Controlled multi-domain and software-engineering rollouts

**General AgentBench trajectories**

- Primary source: [dataset card](https://huggingface.co/datasets/cx-cmu/agent_trajectories).
- Verified scope: 8,653 cleaned trajectories over tau2bench, swebench,
  terminalbench, mathhay, search, and mcpbench. Each task/model pass is a fresh
  attempt, not a fork from shared history.
- Useful fields: full messages/tool calls, task/reward/evaluation details, model,
  domain, and pass.
- Scientific use: cross-domain failure and state-operation comparison.
- Limits: exact per-run tool menu is not always reconstructable; no lifecycle or
  authority semantics; gated access.

**Microsoft Orchard**

- Primary source: [dataset card](https://huggingface.co/datasets/microsoft/Orchard).
- Verified at public revision
  `70c05ec1f20f823ae6adc60374922e9271bb74e2`: 107,185 SWE trajectories over
  2,788 repositories, including
  74,649 resolved and 32,536 unresolved rows, plus 3,070 GUI rollout prefixes.
- Viewer-verified SWE schema: `tools`, `messages`, and `metadata`; message rows
  carry `role`, `content`, `tool_calls`, and
  `tool_call_id`.
- Availability: public/ungated under MIT metadata, 19 SWE Parquet shards
  totaling about 9.72 GB plus three GUI shards. One untruncated SWE row/schema
  was inspected through the Viewer; no shard was downloaded.
- Scientific use: large structured positive/negative workload and
  command-detector validation.
- Limits: independent sandbox rollouts; no checkpoint/fork/restore lineage,
  authorization state, protected effect phase, or external receipt.

**AgentRx**

- Primary source: [repository](https://github.com/microsoft/AgentRx).
- Verified evidence: a failure taxonomy including plan adherence, invented
  information, invalid invocation, tool-output misinterpretation, intent-plan
  misalignment, and underspecified intent.
- Scientific use: stratification and manual-label rubric.
- Limits: a taxonomy diagnoses failures but does not identify authority
  continuity or supply complete histories for the target property.

### C. Telemetry and interchange schemas

**Agent LLM Traces**

- Primary source: [dataset card](https://huggingface.co/datasets/DiscoPosse/agent-llm-traces).
- Verified scope at revision
  `6b1add7c19f1fb50bb0edf5b240d6149a5c621fb`: 1,781 traces across six
  benchmarks and five harness families; 39 Parquet shards totaling
  983,592,848 bytes; public, ungated, CDLA-Permissive-2.0 metadata.
- Viewer-verified fields: harness, benchmark, models, session ID, collection
  time, and spans with span/trace IDs, start/end times, model and response IDs,
  input/output messages, tool definitions, token counts, and status.
- Pilot finding: calls/results appear inside cumulative message JSON and must
  be deduplicated by call ID. The current Viewer schema exposes no
  `parent_span_id` and sampled spans contain no independent tool-execution span;
  LLM-span error status is not normalized dispatch/result truth.
- Aggregate workload seeds include distinct payment-request call IDs, a
  ten-query fan-out followed by reservation mutations, repeated identical
  call signatures under different IDs, and empty-output error spans. None is
  labeled as a security violation.
- Scientific use: timing, error, retry-candidate, fan-out, and ordinary
  observability audit.
- Limits: no branch/checkpoint semantics, authority lineage, stable cross-retry
  protected-effect identity, effect phase, trusted receipt, or external-state
  truth. The reproducible offsets/hashes and privacy boundary are in
  `../public-trace-pilot.md`.

**Agent Data Protocol**

- Primary source: [repository](https://github.com/neulab/agent-data-protocol).
- Verified format: tool calls have `function_name`, `arguments`, and
  `tool_call_id`; observations link back with `source_call_id`.
- Scientific use: normalize public traces before adding a small extension.
- Limit: correlation IDs do not specify cross-retry idempotency, authority
  ownership, or durable lifecycle meaning.

### D. Official runtime interfaces

**Codex App Server**

- Primary source: [official protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md).
- Verified fields: `threadId`, `turnId`, item/call IDs, parent-thread metadata,
  `forkedFromId`, source history boundary, and event streams.
- Dynamic tools are experimental. On a tool call, the server sends the client
  `threadId`, `turnId`, `callId`, namespace/tool, and arguments and waits for a
  response.
- Scientific use: leading adapter because the client can own the mock protected
  dispatch instead of observing it after the fact.
- Limit: provider `callId` is call/result correlation; the adapter still needs a
  persistent protected `effect_id` across crash/retry/fork.

**Claude Code checkpointing**

- Primary source: [official checkpoint documentation](https://code.claude.com/docs/en/checkpointing#limitations).
- Verified limitations: rewind does not track Bash-command file changes, most
  subagent edits, external/concurrent-session changes, or symlink/hard-link
  targets.
- Scientific use: direct product evidence that “restore the workspace” is not
  “restore the world,” and that one runtime contains multiple rollback domains.
- Limit: documentation demonstrates boundary mismatch, not an authority
  violation or complete mediation path.

## Inclusion and exclusion decisions

| Asset | Decision | Reason |
|---|---|---|
| SWE-chat | Primary, access pending | Best natural workload and checkpoint/commit/session joins |
| Agent LLM Traces | Include as public schema/timing corpus | Public, structured, small enough for a complete audit |
| Orchard SWE | Include as public large controlled fallback | Structured calls, both resolved/unresolved outcomes, live Viewer; one row inspected, no bulk download |
| General AgentBench | Secondary, access pending | Broad domains but independent passes are not forks |
| AgentRx / coding-agent-misalignment | Include for taxonomy/motivation | Failure labels, not theorem-state traces |
| Agent Data Protocol | Include as normalization baseline | Standard correlation schema exposes the extension boundary |
| Synthetic risk-injected tool traces | Exclude from “real workload” counts | Useful adversarial tests but not evidence of natural prevalence |
| Task/environment repositories without released rollouts | Exclude as trajectory evidence | A benchmark definition is not an observed agent execution |

## Required-field coverage matrix

The proposed audit classifies each field as explicit, assumption-derived, or
absent rather than forcing a Boolean “supported” label.

| Security fact | SWE-chat | OTel traces | Orchard | Codex controlled adapter |
|---|---|---|---|---|
| thread/session and call correlation | explicit | explicit | explicit | explicit |
| checkpoint/save-point ID | explicit | absent | absent | explicit if instrumented |
| typed Fork/Restore operation and source boundary | partial/inferred | absent | absent | explicit |
| branch epoch and active/retired status | absent | absent | absent | extension |
| Merge lineage projection | absent | absent | absent | extension |
| grant/claim identity, demand, status, support | absent | absent | absent | extension |
| protected stable effect ID across retry | not guaranteed by call ID | not guaranteed by response/call ID | not guaranteed | extension |
| Prepare/Dispatch/uncertain/settled phase | absent | partial call/error only | partial call/result only | extension |
| external before/after state and durable receipt | absent | absent | absent | explicit mock sink |

## Novelty and paper impact

The survey does not justify adding a broad benchmark contribution. It supports
a narrower theorem program with a deliberately high promotion bar:

1. define nested observations `O0` (workspace/checkpoint), `O1` (ordinary
   session/call/result telemetry), and `O2` (trusted lifecycle, authority, and
   effect events), together with their observation equivalence;
2. prove ordinary-trace insufficiency with independent `O1`-equivalent witness
   families: replacing/live Restore; fragment-conserving transfer versus two
   child aliases of one inherited claim; and
   success-before-crash/never-dispatched (or retry/new-operation);
3. seek componentwise necessity: removing topology lineage, authority lineage,
   or stable effect identity/phase must recreate a pair with different safe
   decisions;
4. prove conditional replay sufficiency by reconstructing the initial
   `LifecycleState`, each abstract label/successor and decision from
   authenticated, self-contained events, then proving that the concrete edges
   form a `SimulatedTrace`; do not define the trace to contain an opaque copy
   of every checker field; and
5. instantiate the candidate event basis in one dispatch-owning adapter while
   using public data only to justify the workload.

The candidate `O2` bundle is crash-atomically appended outside the checkpoint
domain, includes canonical projection/support/certificate payloads rather than
mutable pointers, and authenticates them against a durable head anchored
outside the rollback domain. Effect reconciliation additionally assumes an
authenticated, idempotent, queryable sink. A hash chain without the anchored
head cannot detect prefix rollback, and a non-queryable sink cannot resolve
the success-before-commit crash window.

The replacing/live pair alone is the existing snapshot indistinguishability
corollary, and “log all checker state then rerun the checker” is tautological.
This becomes a separate contribution only with an irredundant event basis, a
minimal observation quotient, or a comparable information lower bound.

The observation fiber must be keyed by the same requested action, not only the
prefix: `K_i=(alpha(O_i(prefix)), normalize(next_action))`. Alpha-normalization
renames run-local IDs by first occurrence, preserves alias/order structure,
and removes absolute time; action normalization fixes operation, source role,
demand, binding, and same/fresh identity relation. The controlled witnesses are
C13/C14 (replace/live topology before the same Reserve), C16/C18 (shared-grant
versus distinct-fragment lineage before the same second Reserve), and
C02/C03 (never-dispatched versus remote-success uncertainty before the same
`FinalizeAbort(e1)`). Raw session IDs/timestamps or different proposed actions
must not create or destroy a claimed collision.

This would connect the paper's abstract “checkpoint-missing state” result to an
industrial telemetry principle: observability must include authorization
lineage and irreversible effect history, not merely more model reasoning or
more verbose tool logs.

The current paper should not yet claim this theorem or report dataset counts.
It may cite runtime checkpoint limitations as motivation. Promotion to a paper
contribution requires a proof, a reproducible public-schema audit, and an
instrumented adapter result.

## Experiment consequence

The next highest-value concrete experiment is:

- full deterministic census of structured lifecycle/effect-candidate events in
  SWE-chat after access approval, with Agent LLM Traces and Orchard as public
  schema/timing and large controlled controls;
- manually audited detector precision/recall on a stratified sample;
- field-coverage results for the theorem's concrete-refinement premises;
- the fixed 20 deterministic Codex dynamic-tool histories specified in
  `docs/runtime-integration.md`, including crash-before-call,
  success-before-commit, and commit-before-reply cases;
- observation ablations `O0` workspace, `O1` ordinary telemetry, and `O2`
  trusted replay events, evaluated separately from admission policies `P0`
  workspace-only, `P1` split-all, `P2` parent escrow, and `P3` the proposed
  authority-continuity controller.

App Server supplies native thread Fork and client-owned dynamic dispatch; the
adapter, not Codex, defines exclusive/parallel topology, replacing/live
Restore, and certificate-checked Merge. The runtime plan enumerates 20 cases
with one named injection site per effectful case, defines complete
Fork/Restore/Merge/retry/revoke/ticket behavior for every policy, and fixes
commands, version/checksum manifests, raw-result paths, an independent oracle,
and exit criteria. None of those commands is claimed to exist yet.

Primary observation outcomes are mixed-label fibers, decoder abstentions, and
wrong decisions for expected-insufficient `O0`/`O1`, followed by exact
`LifecycleState`/label replay and decision reconstruction for `O2`. Policy
outcomes separately classify true/false accepts/rejects and aggregate mock-sink
outcomes for `P0`--`P3`; only `P3` must match every suite decision and admit no
unsafe history. L1/L8/L10/L13 and mock-sink snapshots form an oracle independent
of controller verdicts. Latency is secondary.

Because SWE-chat and the misalignment study derive from real developer
sessions, the corpus phase must follow the release terms, avoid identity
resolution or cross-dataset deanonymization, report aggregates rather than raw
prompts/code, and obtain institutional ethics/IRB guidance where applicable.

## Remaining uncertainty

- SWE-chat and General AgentBench access has not been granted in this
  environment.
- Command strings are only effect candidates; the study needs manual validation
  and must not infer remote success from syntax.
- It is unknown whether the observability theorem yields a nontrivial
  irredundancy, quotient, or lower-bound characterization beyond the existing
  snapshot indistinguishability result.
- Codex dynamic tools are experimental; production complete mediation may need
  a mandatory MCP proxy or deeper product integration.
- External receipts and aggregate sink outcomes remain trusted assumptions even
  with richer traces unless the mock/real sink exposes them faithfully.

## Next evidence node

Define `O0`--`O2`, prove independent topology/authority/effect witness pairs,
and attempt componentwise necessity. Replay must reconstruct
`LifecycleState` plus abstract labels/successors before proving a
`SimulatedTrace`. In parallel, implement the aggregate-only Agent LLM Traces
scan at the pinned revision, sample or stream Orchard under its public MIT
release, and obtain explicit SWE-chat access if its gated terms are approved.
Only after that proof boundary is stable should the Codex dynamic-tool adapter
be implemented.
