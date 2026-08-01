# Real Agent Trace / Trajectory Dataset Audit

Audit date: 2026-08-01 (America/Vancouver)
Mode: read-only source and artifact audit
Project: `agent-check-restore-safety`
User question, verbatim: “我们需要去看真实的 agent trace / 轨迹数据集吗? 需要的话也可去看看”

## Executive decision

**Decision: useful, but not required for the current CSF theory paper.** We did need to look, because public trace assets can test two empirical premises of the paper: whether real agent workloads contain long-lived execution and orchestration, and whether ordinary telemetry exposes the state needed by the proposed admission rule. The audit found meaningful new evidence, especially UW TraceLab's real Claude Code/Codex telemetry and WebArena's stateful web traces. It did **not** find a public dataset that exposes the joint theorem state: trusted lifecycle lineage, authority/grant lineage, durable support, effect phase and receipt, crash boundary, and sufficient event order.

Therefore:

1. Public traces can strengthen the **motivation and observability-gap** argument.
2. They cannot label a lifecycle operation as safe or unsafe under the paper's model, and cannot replace the fixed Codex adapter validation.
3. A broad trace benchmark would have low paper value and would pull the paper away from its formal contribution.
4. If one small addition is desired, make it a **fixed schema/field audit**, not a benchmark: TraceLab v0.0.2 + SWE-chat's public schema/card + one WebArena-Verified trace family. State clearly that the result is “no single audited trace quotient suffices for exact admission,” not “real agents are unsafe X% of the time.”
5. A native checkpoint/restore experiment using StateFork/Waypoint would be scientifically stronger, but it is a separate, higher-cost systems extension and is not required for the current deadline.

The most important nuance is that individual components do appear in public assets. LangSmith exposes call-tree lineage; LangGraph exposes checkpoint replay/fork; SWE-chat links sessions, checkpoints, branches, and Git commits; WebArena exposes stateful requests and network traces. What is absent is their **trusted joint composition**. The paper should not claim that ordinary traces expose none of these fields individually.

## 1. Claims tested and finite coverage boundary

The audit tested three name-free claims rather than searching for datasets by popularity.

### C1: Exact admission requires a richer trace quotient

Public ordinary trajectories cannot support sound, exact admission for history-transforming execution unless they expose trusted lifecycle lineage, authority/grant lineage, durable support, effect phase/receipt, crash boundary, and event order. This claim would be challenged if a public trace exposed all of those fields with semantics strong enough to replay the paper's admission algorithm.

### C2: Real traces can establish workload relevance

Real traces are useful if they show that deployed agent sessions include long-lived execution, orchestration, retries or recovery, and externally visible effects. This supports the importance of the problem and the instrumentation premise. It does not support the preservation theorem.

### C3: A small audit can be paper-valued without becoming a benchmark

A fixed field-level audit over representative assets can test whether current traces contain the minimum information needed by the formal model. It should not estimate safety prevalence when the decisive latent state is missing.

### Coverage boundary

Included:

- Public or inspectable coding-agent traces.
- Public tool-use, browser, and computer-use trajectories.
- Official telemetry schemas with concrete event semantics.
- Official checkpoint/fork runtimes adjacent to the paper's lifecycle model.
- Primary project pages, repositories, dataset cards, documentation, papers, and release artifacts current on 2026-08-01.

Excluded unless needed to change the decision:

- Benchmark score comparisons and prompting quality.
- Pure task datasets without execution trajectories.
- Hidden proprietary telemetry.
- Synthetic traces, except as controlled schema comparators.
- A bulk census or safety-rate estimate that cannot observe the theorem state.

The six audited information classes were:

1. **Lifecycle:** parentage plus semantically identified Fork/Restore/retry/replay.
2. **Authority:** credentials, grants/capabilities, delegation, attenuation, or revocation lineage.
3. **Durable support:** the durable state on which surviving authority/effects depend, including remote state rather than only a workspace snapshot.
4. **External effects:** stable effect identity, phase, result/receipt, and enough information to distinguish duplication from idempotent replay.
5. **Crash boundary:** where failure occurred relative to local persistence and external visibility.
6. **Order:** sufficient event ordering/correlation for replay or admission.

## 2. Source-search and verification log

Searches were executed on 2026-08-01. Search results were not treated as evidence; each material conclusion below was checked against a primary page, repository, documentation page, dataset card, paper, or release artifact.

Representative exact query strings:

| Purpose | Query |
|---|---|
| Real coding-agent traces | `real world coding agent trajectory dataset Claude Code Codex sessions tool calls 2026` |
| Codex/Claude public telemetry | `site:github.com Codex Claude Code trace dataset trajectories tool calls` |
| TraceLab | `UW SyFI TraceLab coding agent telemetry dataset Claude Codex` |
| SWE-chat schema | `SWE-chat dataset sessions checkpoints commits conversation schema` |
| SWE-bench trace releases | `site:github.com/swe-bench/experiments reasoning traces execution logs trajectories` |
| OpenHands traces | `OpenHands trajectory dataset tool calls issue patches Hugging Face` |
| Orchard | `Microsoft Orchard software engineering trajectories dataset schema` |
| WebArena traces | `WebArena human trajectories Playwright trace network HAR` |
| WebArena-Verified | `WebArena Verified network HAR trajectory logs stateful websites` |
| OSWorld trajectories | `OSWorld trajectory dataset traces release` |
| AgentDojo runs | `AgentDojo public runs trajectories tool calls security task` |
| LangSmith schema | `LangSmith run data format trace parent_run_id dotted_order tool error` |
| LangGraph lifecycle | `LangGraph time travel fork checkpoint replay external API side effects` |
| Native checkpoint/restore | `StateFork Waypoint agent checkpoint restore fork external side effects` |
| General agent telemetry | `OpenTelemetry AI agent trace dataset parent span tool call result` |

Primary assets checked:

- UW TraceLab site: <https://tracelab.cs.washington.edu/>
- UW TraceLab paper: <https://arxiv.org/abs/2606.30560>
- UW TraceLab repository: <https://github.com/uw-syfi/TraceLab>
- UW TraceLab v0.0.2 release: <https://github.com/uw-syfi/TraceLab/releases/tag/v0.0.2>
- SWE-chat project: <https://www.swe-chat.com/>
- SWE-chat dataset card: <https://huggingface.co/datasets/SALT-NLP/SWE-chat>
- SWE-chat paper: <https://arxiv.org/abs/2604.20779>
- SWE-agent trajectory documentation: <https://github.com/SWE-agent/SWE-agent/blob/main/docs/usage/trajectories.md>
- SWE-bench experiments: <https://github.com/swe-bench/experiments>
- Open-SWE-Traces: <https://huggingface.co/datasets/nvidia/Open-SWE-Traces>
- SWE-Zero OpenHands trajectories: <https://huggingface.co/datasets/nvidia/SWE-Zero-openhands-trajectories>
- Microsoft Orchard: <https://huggingface.co/datasets/microsoft/Orchard>
- OpenHands datasets: <https://huggingface.co/OpenHands/datasets>
- WebArena: <https://github.com/web-arena-x/webarena>
- WebArena trajectory resources: <https://github.com/web-arena-x/webarena/blob/main/resources/README.md>
- WebArena-Verified: <https://github.com/ServiceNow/webarena-verified>
- AgentLab: <https://github.com/ServiceNow/AgentLab>
- BrowserGym core API: <https://browsergym.readthedocs.io/latest/core/core.html>
- WorkArena: <https://github.com/ServiceNow/workarena>
- OSWorld-V2: <https://github.com/xlang-ai/OSWorld-V2>
- AgentDojo: <https://github.com/ethz-spylab/agentdojo>
- A concrete AgentDojo run: <https://raw.githubusercontent.com/ethz-spylab/agentdojo/main/runs/gpt-4o-2024-05-13/workspace/user_task_0/none/none.json>
- General AgentBench trajectories: <https://huggingface.co/datasets/cx-cmu/agent_trajectories>
- Agent LLM Traces: <https://huggingface.co/datasets/DiscoPosse/agent-llm-traces>
- AgentRx: <https://github.com/microsoft/AgentRx>
- LangSmith run-data format: <https://docs.langchain.com/langsmith/run-data-format>
- LangSmith trace export: <https://docs.langchain.com/langsmith/export-traces>
- LangGraph time travel: <https://docs.langchain.com/oss/python/langgraph/use-time-travel>
- LangGraph persistence: <https://docs.langchain.com/oss/python/langgraph/persistence>
- StateFork paper: <https://arxiv.org/abs/2510.05556>
- StateFork repository: <https://github.com/Alex-XJK/StateFork>
- StateFork overview: <https://daplab.cs.columbia.edu/general/2026/06/04/statefork-give-agents-a-rewind-button.html>
- Waypoint repository: <https://github.com/Alex-XJK/waypoint>

Access caveats:

- SWE-chat and General AgentBench require accepting Hugging Face access/contact terms. Their public cards and schemas are inspectable, but a full local census was not performed.
- OSWorld-V2 task assets are gated; it is primarily a task/environment release rather than a public trajectory corpus.
- Some SWE-bench experiment logs are delivered through S3 and may require an AWS account.
- The fixed TraceLab v0.0.2 JSONL was publicly downloadable and was inspected locally. The repository README's release pointer lagged the GitHub release list when checked, so the GitHub release page/API was treated as authoritative for the current release.

## 3. What counts as a trace asset

Several things marketed around “agent traces” are scientifically different:

| Asset kind | What it contains | What it can test here |
|---|---|---|
| Task dataset | Initial state, task, oracle/evaluator | Workload coverage, not execution semantics |
| Trajectory corpus | Ordered messages, tool calls/results, possibly patches or screenshots | Workload and observation coverage |
| Telemetry schema | IDs, parents, timestamps, status, input/output conventions | Whether a runtime could expose required state |
| Checkpoint/fork runtime | Snapshot/restore/fork operations and runtime state | Lifecycle mechanism and integration feasibility |
| Protected-effect log | Stable effect IDs, prepare/commit/receipt and remote state evidence | Admission and recovery semantics |

No audited public asset was a protected-effect log. This is the central reason a public trace cannot directly serve as ground truth for the paper's safety property.

## 4. Field matrix

Legend: **Y** = explicit enough for the stated field; **P** = partial, indirect, local-only, or not trusted for admission; **N** = absent; **—** = not a released trajectory corpus. “Order” means reconstructable tool/event order, not necessarily a total order across remote resources.

| Asset | Kind / provenance | Lifecycle | Authority | Durable support | External effects | Crash boundary | Order | Best use in this paper |
|---|---|---:|---:|---:|---:|---:|---:|---|
| TraceLab v0.0.2 | Real opt-in Claude Code/Codex telemetry | P | N | N | P | P | Y | Strongest new real-workload and observability evidence |
| SWE-chat | Real developer sessions linked to Git history | P | N | P | P | N | Y | Checkpoint/commit linkage and natural coding workload |
| SWE-agent / SWE-bench experiments | Controlled benchmark trajectories on real issues | P | N | P | N | P | Y | Patch/evaluation replay, not lifecycle safety |
| Open-SWE-Traces / SWE-Zero / Orchard | Large synthetic or automatically generated SWE trajectories | N | N | P | N | P | Y | Scale control; poor evidence of in-the-wild lifecycle semantics |
| WebArena human trajectories | Human demonstrations on stateful self-hosted sites | N | P | P | P | N | Y | Concrete stateful web interactions and network observability |
| WebArena-Verified | Audited stateful tasks, logs/HAR-based verification support | N | P | Y/P | Y/P | N | Y | Strongest external-state/effect-order comparator |
| AgentLab / BrowserGym | Telemetry/runtime framework, not one fixed public corpus | — | N | P | P | P | Y | Instrumentation pattern only |
| OSWorld-V2 / WorkArena | Stateful task environments; no suitable public trace corpus found | — | P | P | P | N | — | Benchmark workload, not trace evidence |
| AgentDojo public runs | Controlled tool-use security traces over simulated services | N | P | P | P | N | Y | Security-policy and tool-call control trace |
| General AgentBench trajectories | Controlled trajectories; multiple independent attempts | N | N | P | P | P | Y | Cross-domain tool-use control |
| Agent LLM Traces | OTel-style public trace samples | N | N | N | P | P | Y/P | Generic span/tool observability gap |
| LangSmith schema | Deployed trace schema, not public user corpus | P | N | N | P | P | Y | Shows that parent call-tree and dotted order are feasible |
| LangGraph checkpoint records | Runtime lifecycle schema/artifact | Y | N | P | P | P | Y | Direct replay/fork motivation; external calls re-execute |
| StateFork / Waypoint | Native C/R runtime, not a public real-user corpus | Y | N | Y/P | N | P | Y | Closest future native C/R integration target |

Important interpretations:

- **Lifecycle is not just a `parent_id`.** LangSmith parentage represents a nested call/span tree. The paper needs history-transforming lineage: what state was restored or forked, which descendant history was invalidated, and which authority/effects survive.
- **A checkpoint is not automatically Restore semantics.** SWE-chat checkpoints are useful save points linked to commits. They do not specify the semantic rollback boundary or what remote effects remain live.
- **A tool result is not a durable receipt.** It may be an observation, truncated output, exception, or local simulator result. It does not by itself say that a protected remote effect became durable exactly once.
- **An authenticated benchmark account is not a capability lineage.** WebArena/WorkArena may use logged-in identities, but do not record attenuated, use-limited, delegated, or revoked authority as a first-class object.
- **A failed tool call is not a crash boundary.** TraceLab and LangSmith can record errors or missing results, but not the exact relation between local checkpoint persistence and remote effect visibility.

## 5. Fixed TraceLab release audit

TraceLab is the most important incremental source because it is a real, recent corpus of the exact class of systems the user cares about: Claude Code and Codex used in daily development.

### 5.1 Primary verification

The current project page reported, when checked on 2026-08-01:

- 8,058 sessions.
- 743,819 tool calls.
- 665,453 agent steps.
- 46 distinct Claude users and 26 distinct Codex users; the fixed release has 52 unique users after deduplicating users who used both providers.
- Data through 2026-07-24.

These headline totals match the fixed v0.0.2 release published on 2026-07-24. No older artifact is used for the results below.

Release artifact inspected:

- File: `syfi_coding_trace.jsonl.gz`
- Ephemeral local audit copy: `/tmp/agent-trace-scout.L7WLad/syfi_coding_trace-v0.0.2.jsonl.gz`
- Size: 100,939,722 bytes
- Published and locally verified SHA-256: `11ce51ec0a25e3d1d95b025bca2f7d1647e47571eb7cc968acd5fc64d4b4fb65`
- Release URL: <https://github.com/uw-syfi/TraceLab/releases/tag/v0.0.2>

The repository was inspected at commit `4ccd9169b559eaa998396b30580ef81966c07afc` to understand extraction and normalization semantics.

### 5.2 Mechanically observed release facts

The fixed v0.0.2 JSONL contains:

- 665,453 round rows.
- 743,819 tool records.
- 8,058 sessions: 5,319 Claude and 2,739 Codex.
- 52 deduplicated users.
- 923 sessions containing at least one tool from the predeclared narrow subagent vocabulary (`Agent`, `TaskOutput`, `wait_agent`, `spawn_agent`, `TaskStop`, `close_agent`, `SendMessage`, `send_message`, or `list_agents`). This is an observability count, not a count of semantic Fork operations.

Most frequent relevant tools include:

- `exec_command`: 251,630.
- `Bash`: 158,610.
- `write_stdin`: 75,975.
- `Read`: 63,984.
- `exec`: 46,757.
- `Edit`: 36,713.
- `apply_patch`: 32,332.

Orchestration-like tool records include:

- `TaskUpdate`: 8,853.
- `TaskCreate`: 4,877.
- `Agent`: 2,546.
- `wait_agent`: 1,045.
- `SendMessage`: 748.
- `spawn_agent`: 664.
- `TaskOutput`: 647.
- `TaskStop`: 500.
- `send_message`: 550.
- `close_agent`: 402.

This is useful evidence that real coding-agent workloads contain orchestration and long-lived process interaction. It is not evidence that any specific event is a semantic Fork, Restore, or authority delegation, because the released tool inputs are removed.

The complete union of released per-tool keys was:

- `emitted_at`
- `command_exit_code`
- `command_skeleton`
- `command_status`
- `continuation_of_tool_call_id`
- `executable_parse_reason`
- `executable_parse_status`
- `executables`
- `input_chars`
- `is_error`
- `result_at`
- `result_chars`
- `tool_call_id`
- `tool_index`
- `tool_internal_latency_ms`
- `tool_name`
- `tool_wall_latency_ms`

There is no released lifecycle `parent`, `fork`, `restore`, `checkpoint`, `grant`, `capability`, `claim`, `effect_id`, `attempt`, `phase`, `receipt`, or crash-boundary field. Version v0.0.2 adds sanitized command structure: 423,280 calls have such structure and 75,488 records identify process continuations. These improve workload classification, but they do not reveal raw commands, resource identity, remote state, or semantic agent lineage. Full tool inputs and outputs remain deliberately stripped for privacy.

Tool-result status combinations included:

- 568,444 non-error tools with a result timestamp.
- 35,453 error tools with a result timestamp (4.77% of tool records).
- 139,153 tools with null error status and a result timestamp.
- 769 tools with null error status and no result timestamp.
- 4,228 sessions containing at least one tool marked as an error.

The 769 missing-result records cannot be interpreted as a crash rate. Missing results can arise from extraction, truncation, cancellation, abrupt session end, or actual failure. More importantly, none of these alternatives locates the failure relative to remote durability.

Trace event counts included:

- 743,819 `tool_call` events.
- 743,222 `tool_result` events.
- 392,632 `reasoning` events.
- 360,008 `usage_report` events.
- 353,702 `text` events.
- 95,446 `user_message` events.

All released tool-call IDs are present and there are no within-session duplicate tool-call IDs, which makes local event correlation reliable. The extractor recognizes subagent metadata such as `parent_thread_id` internally for replay/deduplication, but the normalized public rows do not retain a usable parent-child lifecycle relation. Likewise, `continuation_of_tool_call_id` denotes process interaction such as `exec_command` followed by `write_stdin`; it is not agent checkpoint restoration.

### 5.3 What TraceLab supports and cannot support

It supports:

- Real Claude Code and Codex sessions, rather than benchmark-only traces.
- Ordered tool use and timing at meaningful scale.
- Real multiagent/orchestration tool names.
- The empirical claim that privacy-preserving telemetry often removes semantic content needed for lifecycle safety checks.

It cannot support:

- A frequency of unsafe Restore/Fork/Merge operations.
- Whether a command changed a protected remote resource.
- Whether an observed error occurred before or after remote commit.
- Whether a child inherited, delegated, or exceeded authority.
- Whether a tool retry duplicated an effect.
- Exact replay of the paper's admission algorithm.

## 6. Other representative findings

### 6.1 SWE-chat: best natural checkpoint-to-result linkage

The public site and dataset card describe real developer sessions with full conversational structure and links among sessions, checkpoints, branches, and Git commits. The public card currently describes 205 repositories, 13,406 checkpoints, 5,851 sessions, 14,459 commits, and 2,692,480 conversation records. Records include ordered turn numbers, timestamps, tool-call IDs, continuation indicators, branch and checkpoint identifiers, and links to commits.

This is unusually useful for connecting interactive agent work to durable Git results. However, the checkpoint is an “entire save point” in the data model, not a semantic statement that the world was restored. Git commits cover repository state, not credentials, processes, job queues, deployed services, messages, payments, or other remote effects. The trace lacks grant/claim lineage, stable protected effect IDs, phase/receipt, and crash boundaries. Full data access is gated, so a new full-corpus study also carries access and privacy-governance cost.

### 6.2 SWE-bench/SWE-agent and large generated SWE corpora

SWE-agent `.traj` files record thought/action/observation turns plus configuration, logs, and predictions. SWE-bench experiment submissions can include reasoning traces, execution logs, predictions, and all best-of-kk rollouts with a selection mechanism. Open-SWE-Traces, SWE-Zero OpenHands, and Orchard add scale and ordered tool interactions over real repositories/issues.

These are useful controlled executions, but most “multiple trajectories” are independent attempts rather than branches from a common durable history. Their durable target is normally a sandbox patch plus evaluator result. They do not observe remote side effects or authority provenance. Open-SWE-Traces and SWE-Zero are explicitly marked synthetic/generated; they should not be presented as natural deployment evidence.

### 6.3 WebArena/WebArena-Verified: strongest external-state comparator

WebArena publishes 179 human trajectories as Playwright trace archives, including concrete browser state and network behavior. WebArena-Verified provides audited stateful tasks and verification support with network HAR/log artifacts. These assets show that an evaluation environment can expose stateful website interactions and request order beyond a local filesystem.

This falsifies an overly broad claim that public agent traces never expose external state or network effects. The correct conclusion is narrower: these traces do not jointly expose lifecycle transformations, capability provenance, stable protected effect identity, idempotency/duplication semantics, and crash position. Self-hosted benchmark reset/evaluation also differs from the durable multi-owner world in the paper.

### 6.4 LangSmith and LangGraph: component fields exist in deployed schemas

LangSmith's documented run format has run/span IDs, `trace_id`, `parent_run_id`, dotted order, start/end timestamps, errors/status, inputs/outputs, and tool-run types. It demonstrates that hierarchical call correlation and precise event order are practical. A call-tree parent is not a lifecycle parent created by Fork or altered by Restore.

LangGraph explicitly supports time travel: replay or fork from a checkpoint, while nodes after the selected checkpoint execute again, including LLM calls, API calls, and interrupts. Its persistence layer records checkpointed graph state, thread history, and pending writes for fault recovery. This is direct real-runtime motivation for the paper: restoring graph state does not automatically restore the external services that later nodes contacted. It is a runtime/schema rather than a public real-user trace corpus, and it has no built-in capability/effect-receipt semantics sufficient for the paper's exact check.

### 6.5 AgentDojo: security-labeled tool trajectories are still not authority histories

AgentDojo publishes concrete ordered runs containing messages, tool calls/results, errors, and utility/security outcomes over simulated workspace, banking, travel, and messaging services. It is a good security and prompt-injection control. Its task/security labels do not encode grant provenance, delegation, attenuation, revocation, or lifecycle transformations. It can test whether policy-relevant tool data are logged, but not the paper's authority-follows-durable-support invariant.

### 6.6 StateFork/Waypoint: closest future integration, not a trace dataset

StateFork introduces native snapshot/restore/fork abstractions for agent execution; Waypoint captures local filesystem, process, shell, and PTY state. Its design and paper explicitly recognize external side effects and services as a boundary requiring fork-aware services or interception. This is very close to the paper's systems motivation.

It is not evidence that current public trajectories contain the missing authority/effect state. It is instead the strongest candidate for a future native C/R evaluation in which the proposed checked operations mediate a real checkpoint tree and a deliberately instrumented remote service.

## 7. Claims supported, challenged, or left unidentifiable

### Supported

- Real Claude/Codex workloads do include long sessions, process continuations, and multiagent/orchestration operations.
- Current public telemetry is usually rich enough for execution ordering and debugging, but poor at durable authority/effect provenance.
- Restoring local/runtime state while later API or tool nodes re-execute is a real runtime pattern, not only a hypothetical semantics.
- External state can sometimes be observed in benchmark-specific logs/HAR files, so a protected-effect adapter is implementable in principle.

### Overbroad versions challenged by the audit

- “Ordinary traces never expose lineage” is false. LangSmith exposes call-tree parentage and ordered spans.
- “No public trace links checkpoints to durable results” is false. SWE-chat links checkpoints/branches/sessions to Git commits.
- “No public trace exposes external effects” is false. WebArena Playwright/network traces and WebArena-Verified HAR/evaluator artifacts expose some external requests and state.
- “No agent runtime supports fork/replay” is false. LangGraph and StateFork provide explicit lifecycle mechanisms.

The defensible claim is: **no audited public asset exposes the complete, trusted joint quotient needed for exact admission across lifecycle, authority, and protected effects.**

### Unidentifiable from public traces

- Prevalence of unsafe rollback/fork/merge.
- Number of duplicated durable effects caused by retry or restoration.
- Whether a surviving credential is semantically supported by the restored durable history.
- Whether a rejected/accepted operation would be correct under the paper's model.
- Completeness of a Codex/Claude adapter for all external resources.

Absence of these labels is not empirical evidence that the property is rare or common. It is an observability result.

## 8. Recommended action

### 8.1 For the current paper

Do not add a broad dataset experiment. Preserve the current evidence hierarchy:

1. Formal model, boundaries, and preservation results.
2. Executable lifecycle/admission model.
3. Fixed Codex adapter showing that current runtime events can be projected into the model, with explicit non-complete-mediation caveats.
4. At most, a compact public-trace observability audit as supporting evidence.

If the 12-page budget is tight, the trace audit belongs in a technical report, appendix, or durable project note. The main paper needs at most one carefully qualified statement in motivation/related work after citation verification: recent real Claude Code/Codex telemetry shows substantial orchestration, while public normalized records omit lifecycle parentage, authority provenance, and protected-effect receipts.

### 8.2 Minimal additional trace experiment, if desired

**Objective:** test observation coverage, not safety prevalence.

Freeze three representative assets:

1. TraceLab v0.0.2 JSONL, pinned by release hash.
2. SWE-chat's published schema/card; use the gated data only if access terms are acceptable and a full-corpus claim is actually needed.
3. One pinned WebArena-Verified release/example family containing network HAR and state evaluator data.

For each asset, mechanically test the six field classes in Section 1, save the exact detection rules, and manually validate a small stratified sample. Report fields as explicit/partial/absent and state whether an exact admission decision is reconstructable. The expected result is 0/3 complete assets, with different partial components present.

Avoid these invalid analyses:

- Treating `spawn_agent` tool-name counts as counts of semantic forks.
- Treating missing tool results as crash-after-commit events.
- Treating tool errors as duplicated effects.
- Treating Git commits as the complete external world.
- Treating login identity or policy labels as capability lineage.
- Inferring unsafe-operation rates from unobservable latent state.

Estimated incremental cost:

- TraceLab fixed schema scan: low; the 100.9 MB v0.0.2 release has already been inspected for this audit.
- Public card/schema audit of SWE-chat: low; full gated corpus analysis is medium because of access, privacy, scale, and validation.
- WebArena-Verified HAR/state audit: medium; requires a small parser and task-specific interpretation of request/state semantics.
- Paper space: approximately one compact table plus one paragraph in supplementary material; more in the main paper is unlikely to repay the opportunity cost.

### 8.3 Higher-value future experiment

For a later revision or follow-up, integrate StateFork/Waypoint (or an equivalent native C/R runtime) with:

- a queryable, idempotent mock external service;
- stable effect IDs and prepare/commit/receipt phases;
- an adapter that records authority grants/claims and checkpoint lineage;
- the paper's checked Fork/Restore/Merge operations;
- four to six litmus histories covering restore before/after external commit, forked use-limited authority, duplicate retry, merge of incompatible branches, and crash at each protocol boundary.

This would test a native C/R boundary and crash atomicity, rather than only a trace schema. It is likely days to weeks of systems integration, may require privileged checkpoint tooling, and changes the evaluation contract. It is scientifically valuable but not required to make the current formal result credible.

## 9. Final classification

| Question | Answer |
|---|---|
| Did looking at real traces add information? | **Yes.** TraceLab is direct real Codex/Claude workload evidence; WebArena shows external-state traceability. |
| Is a real public trace experiment required for the current CSF claim? | **No.** The formal claim and fixed adapter do not depend on prevalence in a public corpus. |
| Can a public corpus replace the adapter? | **No.** None exposes the joint trusted state needed to replay admission. |
| Is a compact trace audit useful? | **Yes, optionally.** It supports observability-gap and workload premises. |
| Should the paper report an unsafe-trace rate? | **No.** Safety is unidentifiable from the released fields. |
| What is the smallest defensible addition? | A pinned 3-asset, 6-field coverage matrix, preferably outside the 12-page core. |
| What experiment would materially deepen the paper? | Native StateFork/Waypoint C/R plus an instrumented protected external service and crash litmus histories. |

The practical conclusion is not “we do not need traces.” It is: **use real traces to establish workload and missing observability; use the formal model and instrumented adapter/runtime to establish safety.**
