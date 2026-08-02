# Private paper-formation trace audit

## Verdict

The private Codex lineage is useful as a **single longitudinal, real-runtime
case study** of delegation, tool correlation, local mutation, failure markers,
and outward-looking actions during formation of this paper. It is not a sample
of 88 independent tasks, and it cannot support an unsafe-history rate or a
claim that any rollback was safe or unsafe.

The older Claude material is metadata-only. Exact recovery found the session
index but no raw session/action files, so it can establish that earlier paper
iterations existed and when they ran, but it cannot contribute action, tool,
failure, fork, or effect counts.

The recommended evidence package is therefore three deliberately unequal
parts:

1. this private Codex lineage for a detailed longitudinal case;
2. the private Claude index for lifecycle metadata only; and
3. the already completed public TraceLab audit for broader workload and schema
   evidence.

Do not pool their denominators or imply that they expose equivalent fields.

## Frozen selection and evidence contract

- Unit of analysis: one interactive parent task and its recursive delegated
  descendants, not individual rollout files as independent tasks.
- Pre-pilot cutoff: repository commit `5efc4ea`, whose commit timestamp is
  **2026-08-02T03:11:01Z**.
- DB selection: the root task plus recursive spawn descendants whose
  `created_at` is at or before the cutoff.
- Maximum selected DB `created_at`: epoch `1785639472`, or
  **2026-08-02T02:57:52Z**.
- Event selection: each local thread header plus its structurally identified
  native turn suffix, then events at or before the cutoff.
- Source is live, but the cutoff and selected-prefix digest freeze the reported
  prefix. Post-cutoff audit activity is excluded.
- Content policy: prompt/message text, reasoning text, tool arguments, shell
  commands, tool-result bodies, raw IDs, raw rollout paths, patch paths, code,
  credentials, and remote names are neither emitted nor copied.

The redacted aggregate is in `summary.json`; the read-only extractor is
`extract_private_paper_traces.py`.

## Crucial source-fidelity finding

A Codex delegated rollout is not simply an independent JSONL stream. In this
version it has:

1. a child-local `session_meta` header;
2. a copied parent-history region, whose timestamps are rewritten close to the
   fork time; and
3. the child-native turn, beginning at the last `task_started` before the first
   `inter_agent_communication_metadata` trigger.

Therefore neither whole-file counting nor “start at the matching session meta”
is valid. The matching header occurs before the copied region. Timestamp-only
deduplication is also invalid because copied events receive new timestamps.

All 88 selected files had exactly one matching local header and a detectable
structural native boundary. Seventy-eight files contained a nonempty inherited
region. The extractor excluded **219,142 inherited rows** and retained **39,160
valid native rows**. The retained prefix has SHA-256
`ca43ab96d87a4027309fdb46e07b518a0e5682e4816411b5755f472e028b6e25`.
Two retained rows in two files failed UTF-8 decoding; no bytes or paths are
reported. These anomalies are trace-integrity facts, not agent failures.

This correction invalidates the initial whole-file/native-header count of
258,302 valid rows. No action or lifecycle number from that naive pass is used
below.

## Exact Codex aggregate at the cutoff

### Lineage

- 88 threads and 87 persisted spawn edges.
- Depths: 1 parent at depth 0, 85 children at depth 1, and 2 children at depth
  2.
- Creation range: 2026-07-26T22:59:05Z through 2026-08-02T02:57:52Z.
- All 88 selected records name the same model family; 87 are delegated children
  and one is the interactive parent.

### Tool protocol and orchestration

- 6,064 call events: 4,673 custom calls and 1,391 function calls.
- 6,064 result events: all result events match a known call ID.
- There is one call without a result and one second result for a previously
  matched call. This arithmetic explains why total calls and results are equal;
  it must not be simplified to “complete one-to-one correlation.”
- No call ID repeats among call events within a thread.
- Main call categories: 4,673 execution wrappers, 96 `spawn_agent`, 475
  `send_message`, 502 `wait_agent`, 160 `list_agents`, 81 execution waits, 35
  follow-up tasks, 18 web runs, 12 interrupts, and 12 legacy shell calls.
- The 96 spawn-call events and 87 persisted lineage edges are different
  observables. A spawn invocation is not itself proof that a durable child edge
  was created.

### Lifecycle and failure-shaped observations

- 132 task starts, 114 task completions, 13 aborted turns.
- 47 context-compaction events and 47 corresponding compacted records.
- 1 UI `thread_rolled_back` event.
- 604 subagent-activity events and 691 inter-agent metadata records.
- Across execution-wrapper results, 4,485 contain a standard completion marker,
  97 contain an explicit failure marker, and 91 use a non-list result shape.

These are protocol observations. Context compaction is not checkpoint/restore;
the UI rollback event is not a semantic Restore; an explicit tool failure is
not a crash-after-effect; and the trace provides no stable operation identity
with which to identify retries safely.

### Workspace and outward-looking action shapes

- 752 `patch_apply_end` events report success, covering 899 aggregate change
  entries. This is repeated mutation activity, not 899 unique files.
- Lexical execution-wrapper classifiers found 1,668 build/test wrappers, 772
  shell-mutation wrappers, 327 Git-inspection wrappers, 599 network/download
  wrappers, 46 process/service wrappers, and 29 database wrappers. Categories
  overlap.
- There are 15 wrappers containing Git-commit syntax and 14 containing Git-push
  syntax. Result markers are available for 14 and 13 respectively: each group
  has one explicit failure marker; 13 commit wrappers and 12 push wrappers have
  a standard completion marker. A standard wrapper completion is still not a
  remote durability receipt.
- The repository currently exposes 12 reachable commits in the case window and
  71 reachable commits across all refs. This is independent repository outcome
  evidence, not a causal mapping from a wrapper to a commit or proof of a
  successful remote push.

Lexical counts are conservative telemetry shapes, not executed-effect counts.
They may match syntax in a wrapper containing multiple nested operations; the
extractor never emits the underlying command.

## Exact Claude recovery result

The old paper-project index has 45 unique, non-sidechain entries and an index
message-count sum of 180. Entries span 2026-01-30T07:38:06.713Z through
2026-02-03T08:59:53.590Z; the latest index modification is
2026-02-03T08:59:55.908Z.

Recovery was exact-ID based:

- 0 of 45 declared raw paths exist;
- an exhaustive filename/path-component scan under the user home found 0 exact
  ID candidates and observed no walk errors;
- all 11 Claude project indices parsed; only the target index references these
  IDs;
- project content search found only the target index, not a raw JSONL;
- backup, file-history, debug, session, task, todo, shell-snapshot, telemetry,
  usage, plugin, cache, job, daemon, and IDE stores yielded no exact-ID raw
  candidate;
- prompt-history metadata references 6 of the 45 IDs, but it contains no usable
  tool/action lineage.

Fuzzy path or content hits were excluded because they do not establish session
provenance. Consequently Claude contributes no tool, mutation, retry, fork, or
external-effect statistic.

## Mapping to the three state planes

| State plane | What this trace exposes | What is still missing |
|---|---|---|
| Reconstructable workspace state | `world_state` records, patch completion records, patch change cardinality, and Git/workspace command shapes | A declared checkpoint manifest, complete resource closure, snapshot version, and proof that every reconstructable resource was captured |
| Durable controller/authority state | Persisted parent-child edges, thread identity, task start/complete/abort, goal updates, compactions, one UI rollback, and call/result correlation | Monotone grant/claim epochs, owner and root-slot bindings, plan hash/version, closed-branch facts, authority provenance, consumed claims, and restore admission records |
| External reality | Outward-looking wrapper shapes and returned wrapper markers; current reachable Git history | Stable protected-operation identity, prepared/dispatched/settled phase, remote before/after state, durable receipt, idempotency or compensation contract, and crash-relative effect boundary |

The case directly demonstrates why a workspace snapshot is not the agent's
complete security state: the same lineage also has controller topology and
external-operation evidence, neither of which is reconstructed by restoring
files.

## Mapping to Plan / Fork / Restore / Prepare / ticket

- **Plan:** four goal-update records exist, but there is no authoritative plan
  graph, target-plan assertion, plan hash/version, owner/root binding, or proof
  that a resumed action belongs to the currently admitted plan.
- **Fork:** 87 persisted spawn edges provide real topology, and copied history
  makes fork provenance operationally visible. The records do not establish a
  capability split, grant conservation, resource closure, or branch epoch.
- **Restore:** one UI rollback and 47 compactions exist, but neither encodes a
  checkpoint ID, a restoration cut, restored resources, target version,
  authority validation, or external reconciliation. They cannot instantiate
  the formal Restore transition.
- **Prepare:** no durable prepare boundary or admission certificate is present.
  Ordinary “about to call a tool” history is not a crash-stable Prepare record.
- **Ticket:** call IDs correlate invocations and results, including one missing
  result and one duplicate result. They do not bind retries to a stable
  protected operation, survive restore as consumed claims, name an effect
  phase, or carry a durable receipt. A call ID is therefore not the paper's
  effect ticket.

## What can and cannot be reported

Safe, reproducible claims:

- one paper-formation task used a real recursive delegation lineage of the
  stated size and depth;
- native histories contain the exact aggregate lifecycle/tool/workspace shapes
  above;
- full-history child logs require structural deduplication;
- ordinary telemetry correlates calls/results and records some topology,
  failures, compactions, local mutations, and outward-looking action shapes;
- the schema lacks the authority and effect fields required to reconstruct the
  formal admission decision.

Unsupported claims:

- prevalence across users, projects, agents, or 88 independent tasks;
- an unsafe-restore, duplicate-effect, retry, or rollback-safety rate;
- exactly-once effects, successful remote durability, or full rollback;
- authority conservation, capability non-amplification, or Plan validity;
- causality between multi-agent orchestration and paper quality or safety;
- equivalence between the private Codex case, private Claude metadata, and a
  public normalized dataset.

## Relation to the public TraceLab evidence

The separate pinned TraceLab v0.0.2 audit reports 665,453 rounds, 8,058 sessions
from 52 deduplicated users, and 743,819 tool records, including 35,453 marked
errors and 75,488 process-continuation records. That corpus supplies broader
workload and ordinary-schema evidence. It still lacks trusted semantic
Fork/Restore parentage, grant/capability lineage, protected-effect phase,
durable receipts, and a crash-relative external-effect boundary.

Use TraceLab for breadth and this private Codex lineage for longitudinal
mechanism shape. Keep Claude metadata as historical context only. The public
audit is at
`docs/tmp/writing/step-0005-20260801T150830-0700/trace-dataset-scout/trace-dataset-audit.md`.

## Concrete extraction, tests, and runtime instrumentation

### Reproducible local pipeline

1. Resolve the cutoff from the pinned repository commit timestamp.
2. Open the Codex SQLite store in read-only mode and recursively select the root
   lineage at that cutoff.
3. For every child, retain the local header, identify the structural native
   boundary, discard the copied parent region, and time-filter only the native
   region.
4. Parse enums and IDs in memory; emit whitelisted counts only. Classify wrapper
   source lexically without emitting it.
5. Join calls/results within each thread; separately count missing and duplicate
   results.
6. Audit Claude only by exact indexed IDs; stop at metadata when raw provenance
   cannot be recovered.
7. Run privacy assertions and emit JSON to stdout. Never copy raw trace rows.

### Tests to retain

- Synthetic fixture with `local header -> copied parent -> task_started ->
  trigger -> child native events`; assert copied calls are not counted.
- Variants for no-history forks, depth-2 forks, multiple copied session headers,
  invalid UTF-8, an out-of-cutoff append, a missing result, and a duplicate
  result.
- Arithmetic assertions: depth counts sum to threads; edges equal selected
  non-root nodes; selected top-level event counts sum to selected valid rows;
  call/result mismatch arithmetic is explicit.
- Determinism test at a fixed cutoff. Two consecutive core replays produced the
  same SHA-256:
  `a1a1b7548471ab2d9e73dfba577e3607f5ffa8f515f0620807cb15befe97c105`.
- Privacy denylist over all emitted string values: no root/session/thread ID,
  UUID-shaped value, home path, prompt, message, command, code, result body,
  patch path, credential, or remote name.

### Minimum runtime telemetry contract

For an industrial adapter, add durable records rather than trying to infer them
from prose or commands:

- common envelope: runtime task ID, monotone event sequence, durable controller
  version, parent event, wall-clock time, and schema version;
- Plan: immutable plan ID/hash/version, node ID, owner, root slot, required
  capabilities/resources, and plan-validity certificate;
- Fork: parent/child branch IDs, generation/epoch, exact snapshot manifest,
  authority split/grants, and resource-closure digest;
- Restore: checkpoint ID, target branch/version, restored resource manifest,
  current-vs-checkpoint controller comparison, rejected reason, and admission
  certificate;
- Prepare/ticket: stable protected-operation ID, ticket ID, idempotency key,
  claim/grant provenance, operation class, and precondition digest;
- effect lifecycle: `prepared`, `dispatched`, `uncertain`, `settled`, or
  `compensated`, plus effect-specific durable receipt and reconciliation result;
- completion: post-state version, consumed-claim record, branch closure, and
  commit/abort reason.

This instrumentation would let a runtime check the paper's admission algorithm
online and let an offline checker distinguish “unknown” from “safe” or
“violating.” The current traces can only motivate and test the parser around
that contract; they cannot retroactively supply the missing security state.

## Method retrospective

The first parser assumed that a matching child `session_meta` began the native
suffix. Direct schema inspection falsified that assumption: the local header is
prepended before copied history. The correction changed the valid-row
denominator from 258,302 to 39,160. This is a general extractor failure mode
worth preserving as a regression test: **forked full-history logs require an
explicit provenance/boundary contract, not ID- or timestamp-only deduplication**.

No raw trace and no canonical paper/document file was modified. No skill or
runtime change is proposed from this single case without an independent replay
fixture and checker-backed acceptance test.
