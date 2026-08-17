# Private paper-formation trace audit, v3 repaired method

## Verdict

The repaired package supports a **retrospective, fixed-cutoff, single-case
study** of one author-operated paper-formation lineage.  It can characterize
the shape of a real Codex workload and the limits of its ordinary telemetry.
It cannot estimate prevalence, label any history transformation safe or
unsafe, or validate the paper's proposed safety algorithm.

`summary.json` now uses schema v3 and supersedes both earlier aggregates.
The v1 counts lacked a pinned boundary and collapsed duplicate IDs.  Independent
review then found that v2 let timestamp-invalid rows choose the boundary,
accepted a false spawn trigger, reopened live files across two passes, and did
not validate output keys.  No v1 or v2 number should be cited.  The corrected
v3 extraction was performed twice with the same private inputs; both the JSON
bytes and all source/edge/cutoff commitments were identical.  A fresh
independent attack then found complete-path schema, targeted-walk error, and
external-root-parent endpoint gaps.  Those attacks are now maintained
regressions, the package passes all 60 current tests, and the private paired
extraction has been refreshed.  This state is ready for final independent
re-review.  Raw traces remain private and were neither copied nor emitted.

## Evidence design

Three evidence layers have different jobs:

| Evidence layer | Proper role | It does not establish |
|---|---|---|
| Private self-hosted Codex lineage | Longitudinal workload shape, fork-log normalization, instrumentation-gap discovery, parser-derived test cases | Population rates, independent replication, safety efficacy, causality, or exactly-once effects |
| Public TraceLab audit | Reproducible breadth for generic tools, errors, continuations, and ordinary schema fields | Semantic Fork/Restore lineage, authority ownership, effect tickets, or crash-relative ground truth |
| Synthetic fixtures | Boundary, cutoff, lineage, accounting, determinism, and privacy regressions | Ecological prevalence or runtime safety |

The formal model and controlled runtime fault injection must carry the security
and algorithm-correctness claims.  Neither observational corpus can do so.

## Retrospective selection and commitments

- Unit of analysis: one selected root and every recursive spawn descendant
  whose DB `created_at` is at or before the fixed cutoff.
- Design: retrospective fixed-cutoff case study, not preregistration and not a
  statistically sampled task population.
- The cutoff is derived from a repository commit that predates the current
  trace pilot.  A Git timestamp is author-controlled chronological evidence,
  not an external timestamping service.
- All schema, edge, and thread reads occur inside one read-only SQLite
  transaction.  The selected graph is checked as a rooted, acyclic,
  single-parent tree.  Duplicate edges, multiple parents, a selected-root
  cycle, disconnection, an unknown edge status, or a missing selected endpoint
  (including the selected root's external parent) fails closed.
- The v3 output commits with keyed HMAC-SHA-256 to the selected root, the
  selected edge snapshot (plus any external root-parent edge), and a source
  manifest containing each private source identity, path, every
  output-affecting selected DB field, depth, committed byte length, prefix
  hash, and selected-event hash.
- The HMAC key is not stored in the repository or published in an anonymous
  artifact.  These are keyed private-selection commitments, not anonymous
  proofs.  An external reviewer without the private traces and key cannot
  recompute them.
- Spawn edges have no event timestamp, and no immutable SQLite snapshot was
  retained.  The edge HMAC detects a changed extraction snapshot if the key is
  available; it does not prove what the edge table contained at cutoff time.

Each selected rollout is read once into an immutable in-memory byte image after
checking regular-file identity, size, modification time, and change time before
and after capture.  Boundary discovery, counting, and hashing all use that one
image.  Eighty-four selected files had no parseable future row and were
committed at their observed EOF; four stopped at the first parseable future
timestamp.  An EOF commitment detects a later append across reruns but cannot
prove when a backdated row was created.  This residual limitation is why the
result is a committed retrospective extraction snapshot, not a preregistered
immutable-at-cutoff corpus.

## Source-grounded native-history boundary

The original parser used the first inter-agent metadata record as a heuristic.
That rule is now admitted only under a pinned upstream source contract:

- Codex `rust-v0.145.0`, commit
  `25af12f7e61572b0bc18ddb1008be543b91519b0`; and
- Codex `rust-v0.146.0`, commit
  `e363b08c9175ac1cbe5893615dd2cb9ddf95043b`.

In both revisions,
`codex-rs/core/src/agent/control/spawn.rs::keep_forked_rollout_item` excludes
`InterAgentCommunication` and `InterAgentCommunicationMetadata` when forming
the copied child history.  For legacy-history, multi-agent-v2 subagent logs,
the first inter-agent metadata record therefore cannot originate in the copied
prefix.  It is a source-grounded native marker.  The last `task_started`
immediately before that marker begins the native child turn.

The extractor validates all of the following before counting a file:

1. exactly one `session_meta` header matches the local thread ID;
2. header and DB versions agree and are in the pinned allowlist;
3. history mode is `legacy`;
4. subagent provenance is unambiguous and, when present, is v2;
5. header, structured source, and DB edge agree on the parent; and
6. the matching header, the last physical local task start before delivery,
   and the first delivery marker are exact timestamped rows before the cutoff;
   and
7. the initial delivery marker has `trigger_turn: true`.

Unsupported versions, paginated history, absent or multiple matching headers,
ambiguous source shapes, and parent mismatches fail closed.  The current corpus
does not claim to use a history ordinal: the matching legacy headers do not
contain one.

Crucially, provenance comes from the matching local header, not selection
depth.  The real selected root has user provenance and no DB parent; 87
descendants have subagent provenance.  A synthetic fixture separately proves
that a selected depth-0 root with an external parent is still normalized as a
subagent.  This avoids silently counting copied history merely because a
subagent was chosen as the case-study root.

The real files contain 36 matching headers from 0.145.0 and 52 from 0.146.0;
all 87 subagent headers are legacy/v2.  Every selected file has exactly one
matching header and a supported boundary.  Seventy-eight files contain an
inherited prefix.  The extractor excludes 219,142 inherited rows and retains
39,160 exact timestamped local rows.

## Cutoff and integrity semantics

The physical stream terminates at the first row with a parseable timestamp
after the cutoff.  Rows after that point are never reconsidered, even if they
have a missing, malformed, or older timestamp.  Before the stop point:

- a valid JSON object with a parseable timestamp at or before cutoff is an
  exact event;
- invalid UTF-8, invalid JSON, non-object JSON, a missing timestamp, or an
  unparseable timestamp is an integrity anomaly and is excluded from event
  counts; and
- copied-prefix rows are excluded before event interpretation.

The v3 rerun excludes two UTF-8 anomalies.  It contains no selected
timestamp-less or unparseable-timestamp event because those categories are no
longer admitted as exact observations.  Aggregate committed-prefix size is
464,299,277 bytes, represented only through counts and the keyed source
manifest; no bytes or paths are published.

## Exact v3 Codex aggregate

### Lineage

- 88 selected threads and 87 selected spawn edges.
- Depth distribution: one selected root, 85 nodes at depth 1, and two at depth
  2.
- The root has user provenance; 87 selected descendants have subagent
  provenance.
- Selection times range from 533,516 seconds before cutoff to 789 seconds
  before cutoff.  The aggregate uses relative offsets rather than emitting
  private DB timestamps for every record.

These are 88 files in one recursive lineage, not 88 independent tasks.

### Tool protocol

- 6,064 raw call events: 4,673 custom calls and 1,391 function calls.
- All 6,064 calls have string IDs.  The sum of per-thread unique call IDs is
  6,064, so no call ID repeats within a thread.
- 6,064 raw result events have string IDs, while the sum of per-thread unique
  result IDs is 6,063; one result ID is duplicated within a thread.
- 6,062 within-thread ID groups form strict, kind-compatible
  one-call/one-result pairs.
- Two call events and two result events do not belong to a strict one-to-one
  pair.  The two ambiguous groups correspond to the accounting shapes “call
  without result” and “one call with two results”; raw-total equality does not
  imply protocol bijection.
- There are no singleton call/result kind mismatches.

The strict paired tool totals include 4,671 execution wrappers, 96 spawn calls,
475 sends, 502 agent waits, 160 agent listings, 81 execution waits, 35 follow-up
tasks, 18 web calls, 12 interrupts, and 12 legacy shell calls.  A tool-call ID
correlates trace records; it is not a durable operation ticket, consumed
authority claim, or external receipt.

Among the 4,671 strictly paired execution results, 4,484 have a standard
completion marker, 97 an explicit failure marker, and 90 a non-list shape.
These are wrapper-level observations, not crash-relative effect outcomes.

### Lifecycle, workspace, and outward-looking shapes

- 132 task starts, 114 task completions, and 13 aborted turns.
- 47 context-compaction events and 47 compacted records.
- One UI `thread_rolled_back` record.
- 604 subagent-activity and 691 inter-agent metadata records.
- 752 successful patch-completion records covering 899 aggregate change
  entries.

Lexical wrapper classifiers find 1,668 build/test wrappers, 772 shell-mutation
wrappers, 327 Git-inspection wrappers, 599 network/download wrappers, 46
process/service wrappers, and 29 database wrappers.  Categories overlap.  The
15 Git-commit and 14 Git-push lexical wrappers are syntax shapes, not proved
commits or remote durability receipts.  Result-marker counts are reported only
for strict one-to-one call/result groups.

Context compaction is not checkpoint/restore.  The UI rollback event is not a
semantic Restore.  A spawn invocation is not itself a persisted child edge.
Patch change entries are not unique files.  None of these observations label a
safety violation.

## Claude metadata result

The explicitly supplied historical Claude project index contains 45 unique,
non-sidechain entries and a message-count sum of 180.  None of its 45 declared
raw paths exists.  Exact-ID recovery is implemented in Python so private IDs
never appear in an `rg` command or any child-process argument.

Targeted project, backup, file-history, auxiliary-store, and history-index
scans recover no provenance-valid raw action corpus; only the target metadata
index and six prompt-history ID references remain.  The global filename walk
finds no exact-ID node in the traversed portion but records four walk errors,
so it is not an exhaustive proof of absence.  The targeted content scans and
project-index enumeration record zero traversal/open/read errors in this run;
the extractor exposes those errors explicitly when they occur.

Claude therefore contributes lifecycle metadata only.  It contributes no tool,
mutation, retry, fork, failure, or external-effect count.

## Mapping to the paper's three state planes

| State plane | Ordinary telemetry exposed in this case | Missing typed evidence |
|---|---|---|
| Reconstructable workspace | world-state records, patch completion and cardinality, Git/workspace wrapper shapes | checkpoint manifest, resource closure, snapshot version, proof every reconstructable resource was captured |
| Durable controller and authority | persisted topology, thread/task lifecycle, compaction, goal updates, call/result correlation | owner/root/token lineage, monotone epochs, plan hash/version, consumed claims, branch closure, Restore admission certificate |
| External reality | outward-looking wrapper syntax, wrapper markers, current repository outcomes | stable protected-operation identity, prepared/dispatched/settled phase, idempotency key, durable receipt, reconciliation or compensation result |

The case illustrates why restoring files is not restoration of the complete
agent security state.  It does not contain a controlled checkpoint/restore
pair and therefore cannot show that a particular workspace restore lost
controller or external state.

## Claims permitted and forbidden

After repair, the private case may support only these paper-facing claims:

- one real paper-formation task used a recursive delegation lineage of the
  reported shape;
- pinned legacy child logs copied parent history and required
  provenance-aware normalization;
- the analyzed records exposed topology, local mutation, lifecycle, wrapper,
  and call/result shapes, but did not jointly expose the typed fields needed by
  the formal plan/token/effect admission predicate; and
- copied history representation is not a duplicated occurrence of authority or
  an external effect.

It cannot support:

- prevalence across users, projects, agents, or independent tasks;
- an unsafe-restore, duplicate-effect, retry, or rollback-safety rate;
- authority conservation, discrete-token linearity, Plan validity, or
  exactly-once external effects;
- causal benefit from multi-agent paper writing; or
- equivalence between private Codex, private Claude metadata, and TraceLab.

The schema claim must remain narrow: **the analyzed records did not jointly
expose the typed fields needed by the formal admission decision**.  The
extractor does not prove that every unexamined product field or future runtime
version lacks such information.

## Privacy and double-blind handling

- The extractor has no author-specific Claude path default.  The index path is
  an explicit private argument and is never emitted.
- Raw root, thread, session, call, result, rollout, workspace, and Claude IDs
  remain in memory only.  Exact-ID content scanning is in-process.
- Every emitted dictionary key and string value is checked against a
  path-sensitive output schema.  The cutoff timestamp is allowed only in its
  named field, and 64-hex values only in named HMAC fields; public pinned
  source commits are exact allowlisted constants.  Unknown event, payload,
  tool, model, and effort values fold to `other`.
- Privacy tests reject UUID-shaped values, private paths, and arbitrary free
  strings.  Prompts, commands, code, result bodies, patch paths, credentials,
  and remote names are never output fields.
- Raw traces and the HMAC key are not release artifacts.  The private aggregate
  is author-produced and cannot be independently reconstructed by reviewers.

Before an anonymous submission, scrub repository history and decide whether
the exact cutoff timestamp, official-runtime combination, HMACs, and distinctive
count vector should appear in the artifact.  The paper can report rounded or
selected workload facts and disclose that the raw private case is unavailable.
An ethics/data statement should cover author ownership, incidental third-party
content, minimization, access, retention, and non-release.

## Regression suites and replay result

The 23 maintained synthetic tests, 16 prior independent attacks, and 21 fresh
independent attacks contain no real IDs, prompts, commands, paths, or result
bodies.  Together they cover:

- both pinned source versions and copied-history exclusion;
- unsupported source version and multi-agent version fail-closed behavior;
- a selected root that is itself an externally parented subagent, including
  rejection of a missing external-parent endpoint;
- zero and multiple matching local headers;
- invalid UTF-8, missing and malformed timestamps, and physical future-stop
  behavior, including older or malformed rows after the stop;
- timestamp-invalid boundary rows, false initial triggers, and concurrent file
  mutation during snapshot capture;
- duplicate call IDs, non-string IDs, duplicate result IDs, and call/result
  kind mismatch accounting;
- multi-parent and cyclic lineage rejection;
- depth/edge/event/call arithmetic;
- fixed-fixture byte determinism; and
- complete-path key/value/digest schemas plus path/UUID/free-string denial;
- commitment of DB fields that normalize to the same public label; and
- missing or malformed declared Claude-index fail-closed behavior without
  guessing another source, canonical nonempty session IDs, and explicit file,
  targeted-directory, global-walk, and project-index-enumeration errors.

Validation command and result:

```text
python -m py_compile extract_private_paper_traces.py \
  test_extract_private_paper_traces.py recheck/test_recheck_adversarial.py \
  recheck-v3/test_recheck_v3_adversarial.py
python -m unittest -v test_extract_private_paper_traces.py \
  recheck/test_recheck_adversarial.py \
  recheck-v3/test_recheck_v3_adversarial.py

Ran 60 tests — OK
```

The private v3 extraction was executed twice serially with one fixed cutoff,
one temporary root input, and one temporary HMAC key.  Every rollout was
captured into one in-memory byte image per invocation.  The two output
SHA-256 values are both
`ae4d362b7f4ccc0ae2dedaca703bccc3d9b47fc7b9e8ca40301415040f5ad5a7`;
the source-manifest, edge, and cutoff HMACs also agree pairwise.  Both return
codes were zero.  `replay-evidence-v3.json` records these content-free facts
and the extractor digest.  The temporary root and key were deleted
automatically; no private path, identifier, HMAC value, or key is retained.

A local private rerun requires explicit inputs; placeholders below are not
artifact paths:

```text
python extract_private_paper_traces.py \
  --root-thread-id-file <private-root-input> \
  --commitment-key-file <untracked-private-key> \
  --claude-index <explicit-private-index> \
  --repo <paper-repository> \
  --cutoff-commit <fixed-cutoff-commit>
```

## Method retrospective

The initial matching-header parser overcounted copied history.  A second parser
used an unpinned first-metadata heuristic and unstable malformed-row cutoff.
V2 grounded the fork boundary but independent review found invalid boundary
timestamps, a false-trigger hole, live-file TOCTOU, and incomplete privacy
validation.  V3 changes the scientific contract rather than merely patching
counts:

1. bind the boundary to supported upstream source revisions;
2. decide normalization from local provenance, not selected depth;
3. require exactly one matching header and consistent DB/header parentage;
4. capture one stable byte image per rollout and require exact timestamped,
   true-trigger boundary records from that same image;
5. stop the physical prefix at the first future timestamp and exclude all
   timestamp anomalies from exact events;
6. validate the lineage tree and commit root/edge/source plus every
   output-affecting selected DB field privately;
7. separate raw event, string-ID, unique-ID, duplicate-ID, and strict
   kind-compatible one-to-one counts; and
8. enforce a path-sensitive output schema over keys, values, timestamps, and
   digests.

The reusable lesson is narrow but important: **forked full-history agent logs
need a versioned provenance contract.  History representation, authority
lineage, and external-effect occurrence are different objects and must not be
collapsed by a trace parser.**
