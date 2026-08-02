# Supplemental public agent-trajectory source audit

Audit date: 2026-08-01 (America/Vancouver)

Mode: read-only; primary sources only; no bulk dataset download

Scope: sources beyond the already-audited Trace Commons corpus, with an
explicit re-verification of the current TraceLab release

## Executive decision

**Real traces are useful, but no newly found public corpus changes the formal
experiment contract.** The strongest additional source is SWE-chat: it joins
real coding-agent transcripts and tool calls to checkpoint, branch, and Git
commit records. The most inspectable ungated raw-session complement is
`nmuendler/share-codex`: 4,333 local Claude Code/Codex sessions with 81,057
tool calls and 80,568 tool outputs. The official tau-bench historical runs are
a useful controlled stateful-tool comparator. None of them records the joint
state required to label authority-plan transport as safe or unsafe:

1. a semantic Fork/Restore/Merge/replay edge and its source checkpoint;
2. grant/capability provenance, delegation, attenuation, consumption, and
   revocation;
3. a stable logical operation identity across retries or branches;
4. effect phase relative to a crash (`prepared`, `committed`, `visible`);
5. a durable receipt, plus idempotence or compensation semantics.

Accordingly, public traces can support the paper's workload-reality and
observation-gap premises. They cannot support an unsafe-rollback prevalence
estimate, replay the proposed admission checker, or replace the controlled
Codex + SQLite protected-effect experiment.

## 1. TraceLab count verification

The claimed **8,058 sessions / 743,819 tool calls** is verified. The exact
source is the official [SyFI TraceLab v0.0.2 GitHub
release](https://github.com/uw-syfi/TraceLab/releases/tag/v0.0.2), published
2026-07-24, whose release body states:

- 665,453 agent steps;
- 8,058 sessions;
- 52 pseudonymous users;
- 743,819 normalized tool calls.

The official [TraceLab project site](https://tracelab.cs.washington.edu/)
independently displays the same snapshot. The release API identifies these
immutable assets:

| Asset | Bytes | Published SHA-256 |
|---|---:|---|
| `syfi_coding_trace.jsonl.gz` | 100,939,722 | `11ce51ec0a25e3d1d95b025bca2f7d1647e47571eb7cc968acd5fc64d4b4fb65` |
| `syfi_coding_trace.duckdb` | 160,182,272 | `a7bab286bc640844560850965ccf47975cf66407154132abaab90f27ec9be744` |

The project's earlier complete local scan already matched the JSONL digest and
all four counts; see [the fixed-release audit](/home/yunwei37/workspace/my-paper-work/agent-check-restore-safety/docs/tmp/writing/step-0005-20260801T150830-0700/trace-dataset-scout/trace-dataset-audit.md).

Important citation nuance: the [TraceLab paper](https://arxiv.org/abs/2606.30560)
describes an older roughly 4,300-session / 430,000-tool-call snapshot. The paper
should cite the paper for collection methodology, but the v0.0.2 release or
project site for the exact 8,058 / 743,819 numbers. These numbers are therefore
**verified, not inferred**, and should not be attributed solely to the older
manuscript snapshot.

## 2. Audit questions and field semantics

The audit tests a deliberately stronger condition than “does the dataset have
tool calls?”

- **Call correlation:** can an ordinary call be paired with its result inside
  one execution?
- **Logical operation identity:** is there an identifier whose semantics say
  that two attempts, retries, restores, or branches implement the same
  protected effect? A per-response tool-call ID is not enough.
- **Lifecycle edge:** is an event explicitly a checkpoint, Fork, Restore,
  Merge, or replay, with source and destination lineage?
- **Authority provenance:** is usable authority connected to a grant, owner,
  scope, budget, delegation, consumption, and revocation history?
- **Durable effect evidence:** is the affected external object identified, and
  is the effect's prepare/commit/visibility phase and durable receipt recorded?
- **Recovery semantics:** are idempotence, duplicate suppression,
  compensation, and the crash position relative to external durability
  explicit?

This distinction prevents three invalid substitutions:

1. `tool_call_id` is correlation, not a cross-retry operation ID;
2. a Git or conversation checkpoint is not evidence that Restore happened;
3. a successful tool result is an observation, not necessarily a durable
   receipt from the protected resource.

Legend below: **Y** explicit; **P** partial, local, indirect, or untrusted for
admission; **N** absent; **—** not applicable because the asset is not an
execution-trajectory corpus.

## 3. Candidate matrix

| Source | Provenance and scale | Call/result correlation | Semantic C/R/F/replay | Durable external state | Stable logical operation ID | Authority/grant provenance | Effect phase / durable receipt | Idempotence / compensation | Best defensible use |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| [TraceLab v0.0.2](https://github.com/uw-syfi/TraceLab/releases/tag/v0.0.2) | Real Claude Code/Codex workload telemetry; 8,058 sessions, 743,819 calls, 52 pseudonymous users | Y | N | P | N | N | N | N | Primary real workload and normalized-telemetry gap |
| [SWE-chat](https://huggingface.co/datasets/SALT-NLP/SWE-chat) | Real open-source developer sessions; 5,851 sessions, 13,406 checkpoints, 14,459 commits, 2,692,480 transcript rows | Y | P | P/Y for Git state only | N | N | N | N | Strongest checkpoint-to-durable-Git complement |
| [`nmuendler/share-codex`](https://huggingface.co/datasets/nmuendler/share-codex) | Public local-session export; 4,333 sessions, 81,057 calls, 80,568 outputs; overwhelmingly Codex | Y | P | P | N | N | N | N | Ungated raw call/result and Codex/VS Code schema audit |
| [`claudeset-community`](https://huggingface.co/datasets/lelouch0110/claudeset-community) | Self-described real Claude Code sessions; 114 rows, 14.4 MB | P | N | P | N | N | N | N | Small raw-content sanity sample; redundant for the paper |
| [tau-bench historical trajectories](https://github.com/sierra-research/tau-bench/tree/59a200c6d575d595120f1cb70fea53cef0632f6b/historical_trajectories) | Controlled GPT-4o / Claude 3.5 Sonnet runs over simulated airline and retail services; four JSON files, 52,361,018 bytes | Y | N | P (simulated DB) | N | N | N | N | Stateful protected-tool control, not in-the-wild evidence |
| [Microsoft Orchard](https://huggingface.co/datasets/microsoft/Orchard) | Teacher-generated sandbox rollouts: 107,185 SWE trajectories plus 3,070 GUI decision rows | Y | N | P | N | N | N | N | Large controlled workload; not needed for core claim |
| [NVIDIA Open-SWE-Traces](https://huggingface.co/datasets/nvidia/Open-SWE-Traces) | 207,489 generated OpenHands/SWE-agent trajectories on real repositories/issues | P/Y | N | P (sandbox patch) | N | N | N | N | Scale/control only, not deployment or lifecycle evidence |
| [AIDev](https://huggingface.co/datasets/hao-li/AIDev) | Real GitHub outcomes: 932,791 agentic PRs across 116,211 repositories; no execution trace | — | — | Y (PR/commit/timeline) | N | N | N | N | External durable-outcome motivation only |

No row supplies a replayable authority-continuity admission record.

## 4. Material candidates beyond Trace Commons

### 4.1 SWE-chat: strongest new complement

Primary sources:

- [dataset card](https://huggingface.co/datasets/SALT-NLP/SWE-chat), dataset
  revision `f66cca95b14caaa4177f7ed5eaa424608dadcffa`;
- [original paper](https://arxiv.org/abs/2604.20779).

The dataset is derived from public repositories using the Entire CLI. Its
published relational schema connects:

```text
repository -> checkpoint <-> session -> ordered conversation/tool rows
                    |
                    +-> Git commits, diffs, and code attribution
```

Relevant explicit fields include:

- ordered `turn_number` and timestamp;
- `tool_call_id`, full tool input JSON, extracted command and path;
- `checkpoint_pk`, `checkpoint_ids`, `canonical_checkpoint_pk`;
- session `branch`, `is_continuation`, and transcript identifier;
- checkpoint-to-`commit_sha` lists;
- commit patch, branch, author, file status, and agent/human attribution.

This is the closest public dataset to a joint trace plus durable local outcome.
It is useful for showing that coding-agent “state” spans conversation,
workspace history, checkpoints, and Git results.

It still cannot label the paper's safety property:

- an Entire checkpoint is a captured save point, not a logged semantic Restore
  or Fork event;
- a Git branch is not an agent-runtime branch;
- a repository's `is_fork` is a GitHub repository attribute, not lifecycle
  lineage;
- Git commits omit processes, credentials, deployments, queues, messages,
  payments, and other external resources;
- no field records grant lineage, use budgets, effect phase, durable receipt,
  idempotence, compensation, or crash-after-commit position.

Access is contact-gated on Hugging Face. The public card and schema are enough
for the field audit; a full download is unnecessary unless the paper later
asks a quantitative Git/checkpoint question.

**Recommendation:** worth citing or placing in a compact appendix schema table.
It is not a safety-label dataset and should not become a new main experiment.

### 4.2 `share-codex`: richest ungated Codex raw-session complement

Primary sources:

- [dataset at revision
  `3d8b1397`](https://huggingface.co/datasets/nmuendler/share-codex/tree/3d8b1397c72dbfbf8b04f518064e2c99dde84ca0);
- [exporter at commit
  `8388f413`](https://github.com/nielstron/share-codex/tree/8388f413f90f0ae496cdf1005fc10565c8e780fa).

The pinned card and manifest report:

- 4,333 sessions: 4,314 Codex and 19 Claude Code;
- 81,057 tool calls and 80,568 tool outputs;
- 443 Codex CLI, 3,792 Codex `exec`, 65 Codex VS Code, 4 Codex
  subagent, and 10 Codex MCP sessions;
- 202,056 total messages;
- dataset SHA-256 for `train.jsonl`:
  `37a024018c5f92f789abd7a5d6cc11c95d255ff1580c1266ee06dfcddab2ba97`.

The Dataset Viewer and exporter source show ordinary OpenAI-style correlation:
assistant calls have `{id,type,function}` and tool messages have
`tool_call_id`. Session metadata preserves initial Git branch/commit, Codex
`source_entrypoint`, and the raw session-meta `thread_source` value. Full tool
arguments and outputs are present after best-effort redaction.

This is genuinely useful because it exposes the concrete commands and results
that TraceLab intentionally strips. It can reveal pushes, network calls,
process continuations, MCP use, and IDE-originated work.

Its limitations are decisive:

- the card does not establish a diverse user population; it is one published
  merged export and is heavily dominated by Codex `exec` runs;
- `thread_source` is preserved but the dataset does not document it as a
  semantic Fork/Restore edge;
- tool-call IDs correlate one call/result pair only; no cross-retry semantics
  are assigned;
- raw command output does not attest to durable remote state;
- no authority, effect phase, receipt, crash boundary, idempotence, or
  compensation fields exist.

**Recommendation:** useful in the technical report or as a small manually
checked raw-schema complement. It adds little enough over TraceLab + SWE-chat
that it should not consume main-paper evaluation space.

### 4.3 `claudeset-community`: real content, weak security schema

Primary source: [dataset card at revision
`fe11da9a`](https://huggingface.co/datasets/lelouch0110/claudeset-community/tree/fe11da9ac006d5592378a3d284ee2ed81ffb7578).

The card reports 114 community-contributed Claude Code sessions. Each row has a
session UUID, project, model, Git branch, time range, hashed contributor, and
ordered `exchange` or `compact` turns. Exchange records retain thinking, text,
tool input/output, and `is_error`.

The inspected normalized row shape does **not** retain a per-call ID: tool
records are embedded inside an exchange as `{tool,input,output,is_error}`.
`compact` denotes context compression, not checkpoint/restore. The corpus has
no external-state receipt, lineage, authority, or recovery semantics.

**Recommendation:** do not add it to the paper. It is a useful confirmation
that richer text does not automatically yield the security event algebra, but
SWE-chat and `share-codex` dominate it.

### 4.4 Tau-bench historical trajectories: useful stateful control

Primary sources:

- [official repository at commit
  `59a200c6`](https://github.com/sierra-research/tau-bench/tree/59a200c6d575d595120f1cb70fea53cef0632f6b);
- [original paper](https://arxiv.org/abs/2406.12045).

The official repository publishes four historical-trajectory JSON files:

| File | Bytes |
|---|---:|
| `gpt-4o-airline.json` | 4,114,038 |
| `gpt-4o-retail.json` | 10,813,408 |
| `sonnet-35-new-airline.json` | 10,888,682 |
| `sonnet-35-new-retail.json` | 26,544,890 |

These runs contain ordered messages, function calls, results, expected
state-mutating actions, rewards, and simulated airline/retail database objects.
They are stronger than coding-only traces for demonstrating stateful external
tool semantics.

However, they are controlled benchmark rollouts, not production traces. The
simulated database is reset per run and there is no C/R lifecycle. In the
inspected official GPT-4o airline prefix, a `tool_call_id` was reused across
different functions, underscoring that an LLM/API call identifier must not be
treated as a stable logical effect identity. The files do not record
prepare/commit phases, durable receipts, cross-run idempotency, compensation,
or authority provenance.

**Recommendation:** an optional controlled scenario source if the runtime
pilot later needs airline/retail mutation shapes. The current purpose-built
SQLite protected tool has higher decision value because it exposes exact
effect phase, ticket, retry, and crash boundaries.

### 4.5 Large generated corpora: scale without the missing semantics

[Microsoft Orchard](https://huggingface.co/datasets/microsoft/Orchard), pinned
at dataset revision `70c05ec1f20f823ae6adc60374922e9271bb74e2`, contains
107,185 software-engineering trajectories from teacher models in isolated
sandboxes and 3,070 GUI decision rows from successful browser rollouts. Its SWE
schema has OpenAI-style call/result IDs and its GUI schema has screenshots and
live-site actions. These are generated benchmark executions, not natural
developer sessions, and neither subset logs C/R or protected-effect recovery
semantics.

[NVIDIA Open-SWE-Traces](https://huggingface.co/datasets/nvidia/Open-SWE-Traces),
pinned at revision `9c0e4579a4ee0effa3e5f7a552494a045f29377d`, contains
207,489 generated OpenHands/SWE-agent trajectories on real repository issues.
The inspected OpenHands row has assistant tool-call IDs but its normalized tool
messages rely on sequence rather than retaining `tool_call_id`. Outcomes are
sandbox patches and evaluator labels.

**Recommendation:** neither is worth adding to the current paper. They can
measure tool-loop shape at scale, but TraceLab already supplies real workload
scale and the controlled adapter supplies the missing recovery state.

### 4.6 AIDev: real durable outcomes, not trajectories

Primary sources:

- [dataset at revision
  `68ed5f4b`](https://huggingface.co/datasets/hao-li/AIDev/tree/68ed5f4b80d27a9e057fc57567f38bd322ac73ec);
- [original current paper](https://arxiv.org/abs/2602.09185);
- [official analysis repository](https://github.com/SAILResearch/AI_Teammates_in_SE3).

AIDev contains 932,791 agent-attributed pull requests across 116,211 public
repositories. Its 33,596-PR curated subset adds PR timelines, commits, patches,
comments, reviews, and related issues. This is excellent evidence that agents
cause durable changes to shared GitHub resources.

It does not preserve the agent execution that caused each outcome. There is no
tool call/result chain, checkpoint, retry, crash boundary, credential history,
or link to a stable protected operation. Joining AIDev to an unrelated trace
corpus would not recover those missing semantics.

**Recommendation:** citation-only motivation for external shared state. Do not
put it in the trajectory experiment or claim it observes effects at the
required granularity.

## 5. Lifecycle-capable systems that are not public corpora

This category matters because absence from datasets must not be misstated as
absence from real runtimes.

### Claude Agent SDK sessions

Anthropic's official [session
documentation](https://code.claude.com/docs/en/agent-sdk/sessions) explicitly
supports continue, resume, and fork. A fork gets a new session ID and copies
conversation history. The documentation also states that this branches the
conversation, **not the filesystem**: edits made by a fork are real and visible
to sessions sharing the directory; file checkpointing is separate.

This is unusually strong runtime-grounding evidence for the paper's state-plane
story. It shows that real agent lifecycle identity and workspace state already
diverge. It is not a public corpus of fork executions, and it says nothing
about authority provenance or external-effect receipts.

### LangGraph, StateFork/Waypoint, Crab, and replay products

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
  exposes checkpoints, pending writes, replay, and fork metadata, but no fixed
  public real-user trajectory corpus with protected effects.
- [StateFork](https://arxiv.org/abs/2510.05556) and
  [Waypoint](https://github.com/Alex-XJK/waypoint) implement native sandbox
  snapshot/restore/fork. They are integration targets, not released natural
  trace datasets.
- [Crab](https://arxiv.org/abs/2604.28138) studies semantics-aware C/R over OS
  state and agent turns. This audit did not locate a released trajectory corpus
  containing its turn/effect classifications.
- [Retrace's official documentation](https://docs.retraceai.tech/) describes
  recording and fork/replay, but no versioned open corpus suitable for a
  reproducible paper audit was found.

These sources can support mechanism comparison or motivate native integration.
They cannot be counted as public trace evidence.

## 6. What the sources can and cannot support

### Supported

1. **Workload reality.** Real Claude Code/Codex sessions execute shells, modify
   files, use MCP/network tools, interact with processes, and sometimes spawn
   subagents.
2. **Multi-plane state.** SWE-chat joins conversation, checkpoint, branch,
   workspace, and commit records; Anthropic's SDK explicitly separates session
   forking from filesystem state.
3. **Schema gap.** Current public formats are good at call ordering and local
   debugging, but omit the trusted joint lifecycle/authority/effect quotient
   required by the proposed checker.
4. **External-state feasibility.** Tau-bench and AIDev show that database and
   GitHub outcomes can be observed separately; therefore an instrumented
   protected-effect adapter is practical in principle.

### Not supported

1. the fraction of real Fork/Restore/Merge operations that are unsafe;
2. the number of duplicated real-world effects caused by restore or retry;
3. whether a credential or approval is supported by the surviving history;
4. whether a call result denotes prepare, commit, visibility, or a durable
   receipt;
5. whether an effect is idempotent, compensatable, or the same logical
   operation as an earlier attempt;
6. sound or complete reconstruction of the paper's admission decision;
7. product-wide mediation completeness for Claude Code or Codex.

Missing labels make these properties **unidentifiable**, not rare.

## 7. Recommended incorporation into the CSF project

Use a two-layer evidence strategy:

1. **Primary workload citation:** retain TraceLab v0.0.2, with the exact release
   numbers and digest.
2. **Best complementary schema:** add SWE-chat to the technical report or one
   compact appendix table, emphasizing checkpoint/session/commit linkage.
3. **Runtime-specific motivation:** cite Anthropic's session-fork documentation
   for the concrete distinction between conversation lineage and shared
   filesystem state.
4. **Optional raw sanity check:** mention `share-codex` only if reviewers ask
   whether full raw Codex tool inputs/results change the missing-field result.
5. **Controlled safety evidence:** keep the Codex + SQLite ticketed-effect
   pilot. It deliberately creates the ground truth that public datasets lack.
6. **Do not add a new broad trace benchmark before the deadline.** Claudeset,
   Orchard, Open-SWE-Traces, tau-bench, and AIDev do not close a formal gate;
   large downloads and corpus-wide counts would have low decision value.

The defensible empirical statement is:

> Across audited real coding-agent traces, checkpoint-linked development data,
> and stateful tool-agent runs, ordinary records expose execution order and
> selected durable outcomes but not the joint trusted lifecycle, authority, and
> effect state needed for exact history-transform admission.

Do **not** state that ordinary traces have no lineage, no checkpoint, or no
external state. Individual sources expose each of those partially. The result
is about their missing trusted composition.

## 8. Reproducibility and search log

Primary-source discovery queries included:

- `site:github.com agent trajectory dataset Claude Code Codex sessions tool calls dataset`
- `site:huggingface.co/datasets coding agent trajectories real developer sessions tool calls GitHub issues`
- `coding agent fork session parent checkpoint trajectory dataset Codex Claude`
- `agent checkpoint restore fork replay trajectory dataset public tool calls`
- `tau-bench official GitHub trajectories tool calls results dataset state database`
- `ToolSandbox benchmark trajectories database external tool state official`
- `StateFork Waypoint checkpoint restore agent traces dataset`

Verification used only official dataset cards/APIs, official repositories and
release APIs, official runtime documentation, and original papers. Search-result
snippets and third-party summaries were leads only and are not evidence in the
decisions above.

No large corpus was downloaded. The mechanical checks were limited to:

- Hugging Face repository metadata, `/is-valid`, `/splits`, `/size`,
  `/statistics`, and selected `/first-rows` or single-row previews;
- pinned GitHub repository trees, release metadata, and exporter source;
- a bounded prefix of one official tau-bench trace to check the concrete call
  schema and ID reuse;
- the already-completed local TraceLab v0.0.2 full scan for count/digest
  confirmation.

Pinned revisions inspected:

| Asset | Revision |
|---|---|
| Trace Commons baseline | `112ebd4d03ce852b00e935d523107c3d0c9a65bf` |
| SWE-chat | `f66cca95b14caaa4177f7ed5eaa424608dadcffa` |
| `share-codex` dataset | `3d8b1397c72dbfbf8b04f518064e2c99dde84ca0` |
| `share-codex` exporter | `8388f413f90f0ae496cdf1005fc10565c8e780fa` |
| `claudeset-community` | `fe11da9ac006d5592378a3d284ee2ed81ffb7578` |
| tau-bench | `59a200c6d575d595120f1cb70fea53cef0632f6b` |
| Microsoft Orchard | `70c05ec1f20f823ae6adc60374922e9271bb74e2` |
| NVIDIA Open-SWE-Traces | `9c0e4579a4ee0effa3e5f7a552494a045f29377d` |
| AIDev | `68ed5f4b80d27a9e057fc57567f38bd322ac73ec` |

## Bottom line for the root agent

The trace audit should modestly strengthen, not redirect, the paper: TraceLab's
8,058-session / 743,819-call v0.0.2 scale is directly verified by its official
release and website; SWE-chat is the best additional source because it joins
real tool trajectories to checkpoints, branches, and commits; `share-codex`
confirms that even full raw Codex call/result content plus thread-source
metadata lacks authority and durable-effect semantics. No public source records
semantic lifecycle lineage, cross-retry operation identity, authority
provenance, effect phase/receipt, and idempotence/compensation together.
Therefore use traces for workload and observation-gap evidence, cite the Claude
SDK's conversation-only fork semantics, and keep the controlled ticketed
SQLite adapter as the only place where safety ground truth is constructed.
