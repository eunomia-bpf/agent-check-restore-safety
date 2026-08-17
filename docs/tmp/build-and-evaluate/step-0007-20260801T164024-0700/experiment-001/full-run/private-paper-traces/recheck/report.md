# Independent recheck of the repaired private-trace method

Date: 2026-08-01 (America/Vancouver)

## Verdict

**REVISE.**  The revision fixes the original copied-history heuristic in the
important case: the two pinned Codex revisions really do remove inter-agent
delivery records from forked history, provenance is taken from the matching
local header rather than selection depth, lineage integrity is checked, and
call/result accounting is now correctly separated into raw, string-ID,
unique-ID, duplicate-ID, and strict kind-compatible pair counts.

The current package is nevertheless not ready to make final exact event-count
claims.  Three boundary rows used in the first pass--the matching header, the
`task_started` row, and the first inter-agent marker--may have a missing or bad
timestamp even though such rows are excluded as anomalies in the second pass.
The extractor also accepts `trigger_turn: false` as the initial spawn marker.
Most importantly, it opens every live rollout twice without proving that both
passes saw the same byte snapshot.  A synthetic append between the passes made
the first pass certify one matching header while the second pass counted two.

The published aggregate is internally consistent, and its anomaly vector makes
it unlikely that the timestamp defects changed this particular result.  That
is not a substitute for a fail-closed rerun: the summary does not expose the
first marker's Boolean value, and there is no reviewable paired digest or log
for the asserted real double replay.  Treat all exact native-event and tool
counts as **provisional until the defects are fixed and the private extraction
is rerun twice**.

No raw private trace, identifier, path, prompt, command, or result was read for
this review.  The review used only the four aggregate/method files, official
pinned source, and synthetic fixtures.  It added files only under `recheck/`.

## Reviewed state

The reviewed working files had these SHA-256 digests:

```text
extractor  8b1e616e8cdfb9be5226c7adcc80bb9adbaa542de5c5d2cbc56cc3b80c0c5941
tests      4df9f0cd6060bc42556c75a0f704e63a62797205b50038d9176e29d32ac72098
report     8baf70dffd9bd22d0a576495c9678b60308dc2b8f97e1072f538f0770ae96bdb
summary    93645ab524494d80517ce9886fd165e295825c0fa17174cdc48df157ac2155ad
```

These are content pins for this recheck, not external timestamps or
commitments to the private inputs.

## Validation overview

- Syntax check: **PASS**.
- Existing synthetic suite: **14/14 PASS**.
- Independent summary arithmetic: **24/24 PASS**.
- Independent adversarial suite: **8 PASS, 8 FAIL**.  Failures are contract
  violations, not flaky tests.
- Diff whitespace check: **PASS**.
- The current `summary.json` passes the implementation's value-only privacy
  assertion.
- No author-specific username or absolute author-home literal occurs in the
  four reviewed distributable files.
- No paired private replay outputs, paired output digests, or replay log were
  present to substantiate the report's byte-identical-real-replay statement.

The sanitized command/result record is in `validation.log`; the independent
tests are in `test_recheck_adversarial.py`.

## 1. Pinned source contract

### What passes

The tag dereferences in the extractor are correct:

```text
rust-v0.145.0^{} -> 25af12f7e61572b0bc18ddb1008be543b91519b0
rust-v0.146.0^{} -> e363b08c9175ac1cbe5893615dd2cb9ddf95043b
```

In both pinned revisions, `keep_forked_rollout_item` returns false for both
`InterAgentCommunication` and `InterAgentCommunicationMetadata`, while keeping
`EventMsg` and `SessionMeta`: [0.145.0 source](https://github.com/openai/codex/blob/25af12f7e61572b0bc18ddb1008be543b91519b0/codex-rs/core/src/agent/control/spawn.rs#L47-L80),
[0.146.0 source](https://github.com/openai/codex/blob/e363b08c9175ac1cbe5893615dd2cb9ddf95043b/codex-rs/core/src/agent/control/spawn.rs#L47-L80).
The fork construction applies that predicate before creating the child thread.
Thus a valid top-level inter-agent metadata row cannot come from the copied
prefix under these pinned code paths.

The initial v2 spawn tool constructs its communication with
`trigger_turn: true` and passes it to `spawn_agent_with_communication`:
[0.145.0 constructor](https://github.com/openai/codex/blob/25af12f7e61572b0bc18ddb1008be543b91519b0/codex-rs/core/src/tools/handlers/multi_agents_v2.rs#L54-L66),
[0.146.0 constructor](https://github.com/openai/codex/blob/e363b08c9175ac1cbe5893615dd2cb9ddf95043b/codex-rs/core/src/tools/handlers/multi_agents_v2.rs#L54-L66).
Both regular-turn implementations persist `TurnStarted` (serialized as
`task_started` on the v1 wire format) before processing the turn input:
[0.145.0 ordering](https://github.com/openai/codex/blob/25af12f7e61572b0bc18ddb1008be543b91519b0/codex-rs/core/src/tasks/regular.rs#L47-L62),
[0.146.0 ordering](https://github.com/openai/codex/blob/e363b08c9175ac1cbe5893615dd2cb9ddf95043b/codex-rs/core/src/tasks/regular.rs#L48-L63).
The session then persists delivery metadata immediately before its canonical
agent-message response item.  This supports the intended source-level sequence
for an uncorrupted v2 spawn rollout.

The implementation also correctly:

- accepts only header versions 0.145.0 and 0.146.0;
- requires legacy history and v2 for a subagent;
- requires exactly one matching local ID header in the first observed prefix;
- derives user/subagent provenance from that header's structured source;
- checks header and DB parentage; and
- normalizes a selected depth-0 root as a subagent when it has an external
  parent.

The real aggregate's one user-provenance record and 87 subagent-provenance
records are consistent with a user root and 87 descendants.  This conclusion
does not rely on guessing from depth: a non-root user header would fail the
parent check.

### What still fails

`process_codex_rollout` discovers the header, task start, and metadata marker
before requiring an exact timestamp.  The second pass later excludes those
rows from event counts, but their line positions have already controlled the
region being counted.  Three independent fixtures that require missing-time
boundary rows to fail closed all fail.  A fourth fixture shows that a Boolean
`false` marker is accepted even though the pinned spawn source requires the
initial communication to trigger a turn.

Version strings and header fields are compatibility evidence, not a binary
attestation.  The paper should say "rollouts labeled with the pinned schema and
validated against the pinned source contract," not claim cryptographic proof
that a particular official binary produced every byte.

## 2. Physical cutoff and snapshot integrity

The intended physical rule works on a stable file.  An independent fixture
places a future-timestamp row before a backdated row, a missing-time row, and a
second matching header.  Only the prefix before the future row is counted.
Rows with missing/bad timestamps before that stop are counted only as
anomalies, not exact events.

The implementation is not atomic, however.  It performs a discovery pass,
closes the file, reopens it, and performs a counting/hash pass.  It neither
captures an initial byte limit nor compares inode, size, modification time, or
a first-pass content digest.  The adversarial test appends a second matching
local header on the first close.  The extractor reports
`matching_header_count == 1` from pass one while pass two includes both headers
in the committed prefix and exact-event total.  No exception is raised.

The report honestly labels the design retrospective and acknowledges that an
EOF commitment cannot prevent later appends.  The two-pass race is stronger:
one invocation itself can combine two source states.  Fix it by operating on a
read-only immutable copy/snapshot, or by pinning one file descriptor and byte
limit and verifying identical content digests across any required passes.
Exactly-one-header and boundary validation must apply to those same committed
bytes.

The fixed cutoff also does not prove when a backdated row was appended.  The
proper description remains "retrospective committed extraction snapshot," not
preregistered, immutable-at-cutoff, or selection-bias-free.

## 3. Lineage and commitments

The synthetic lineage attacks pass:

- duplicate selected edges fail closed;
- a non-root with an additional external parent fails closed;
- a selected cycle fails closed;
- a depth-0 selected root with one external parent retains that parent in
  `expected_parent_id`, excludes it from the selected node set, and includes
  the edge in the edge HMAC; and
- the selected tree is checked as connected, acyclic, and single-parent rather
  than inferred only from `edges = nodes - 1`.

Root, edge, cutoff-commit, and source-manifest HMACs are domain-separated and
require at least 32 key bytes.  They are useful private integrity commitments.
They do not prove preselection: the case root was selected retrospectively,
the key is not public, and no externally timestamped commitment is supplied.
An external reviewer cannot recompute them.

The source manifest commits IDs, parent IDs, paths, prefix lengths/hashes,
selected hashes, and several DB provenance fields.  It omits other
output-affecting DB fields, including `created_at`, model, and reasoning effort.
The edge table has no event timestamp and no immutable SQLite snapshot was
retained.  The paper must retain these limitations.  A stronger rerun should
either commit every output-affecting input field or commit a read-only database
snapshot.

## 4. Protocol accounting and the 6,062-pair arithmetic

The accounting repair is correct.  Independent duplicate-call and
kind-mismatch fixtures confirm that only a singleton call plus singleton result
with the required kind relation is a strict pair.  Duplicate groups and
singleton kind mismatches never enter the pair count.

All 24 independently checked identities in the current summary pass.  In
particular:

- 6,064 raw calls partition into 6,064 string-ID calls and zero non-string-ID
  calls;
- 6,064 unique per-thread call IDs plus zero duplicate-call events equals the
  string-ID call total;
- 6,064 raw results contain 6,063 unique per-thread result IDs and one
  duplicate-result event;
- 6,062 strict pairs plus two unpaired calls equals 6,064 raw calls;
- 6,062 strict pairs plus two unpaired results equals 6,064 raw results; and
- strict pair tool totals and the 4,671 execution-result marker total agree.

Given no duplicate call IDs and no singleton kind mismatch, the two ambiguous
groups and these totals force the reported shapes: one one-call/zero-result
group and one one-call/two-result group.  Raw call/result equality therefore
does not imply a protocol bijection.

These labels and equations are paper-ready.  Their **sample values** still
depend on the native event set selected by the flawed two-pass boundary and
must be regenerated after repair.

## 5. Claude recovery boundary

The Claude path is now explicit; there is no author-specific default.  The
extractor does not guess a replacement corpus when that declared index is
missing or unsupported.  Exact-ID content and filename scans are implemented
in Python, so Claude IDs are not passed to `rg` or another child process.  The
summary records four walk errors, so the global filename result is correctly a
partial scan rather than proof of global absence.

The current index schema validation still accepts an empty session ID.  In
that case an empty byte needle matches every nonempty content window, defeating
the meaning of "exact ID".  Require a nonempty canonical ID before scanning.
Also return an explicit error bit from `file_distinct_id_count`; its current
zero conflates absence with an unreadable history file.  The present nonzero
history result shows that this particular file was read, but the API remains
ambiguous.

The command line still permits `--root-thread-id`, which places the private root
ID in the extractor process's arguments.  The reported real rerun used
`--root-thread-id-file`, but a privacy-preserving artifact should remove or
prominently reject the direct-ID form.

The only permissible Claude conclusion remains: the declared historical index
contributes lifecycle metadata, while no provenance-valid raw action corpus
was recovered.  Four walk errors preclude a global absence proof.  Claude must
not contribute tool, mutation, failure, retry, fork, or external-effect counts.

## 6. Privacy and double-blind risk

The output dataflow is substantially safer than v1: unknown event, payload,
tool, model, and effort strings fold to fixed labels; private commands and
result bodies remain internal; the current summary contains no raw path or
session identifier; and no author-specific literal remains in the reviewed
files.

The claimed "complete emitted-value allowlist" is not mechanically complete:

1. `privacy_assertions` walks dictionary values but never dictionary keys.  A
   document with an arbitrary private key is accepted.
2. Any 40- or 64-character lowercase hexadecimal value is accepted in any
   field.  That admits an arbitrary digest-shaped token without establishing
   that it came from an approved digest-producing field.
3. The known-model mapping is visible in source, so `pinned_primary` is a
   reversible label rather than concealment of the exact model.

The current generator mostly uses fixed schema keys and typed digest fields,
so these are defense-in-depth/dataflow gaps rather than evidence that
`summary.json` presently contains a raw secret.  Fix them with a path-sensitive
output schema: validate keys as well as values, allow a digest only at named
digest fields, and decide whether exact model identity is needed at all.

For double blind submission, do not publish the raw traces, HMAC key, private
index, or author-specific paths.  The exact cutoff timestamp, HMAC vector,
pinned runtime/model combination, and distinctive exact count vector can link
an anonymous artifact to a public repository or later disclosure even without
containing a username.  Prefer rounded/selective workload facts in the paper,
withhold the private `summary.json` from the anonymous artifact, and publish
only the extractor, synthetic fixtures, and public-corpus analysis after a
history/path scrub.

The data statement should say that this is one author-operated, non-public case
whose raw content may include incidental private or third-party material; give
the minimization, access, retention/deletion, and non-release policy; and state
that the aggregate is author-auditable but not independently reproducible.

## 7. Replay and determinism

The fixed synthetic fixture and aggregate construction are deterministic on
stable inputs, and both the committed 14-test suite and independent arithmetic
test pass.  The report's stronger statement--that the real extraction was run
twice and produced byte-identical JSON--has no paired output, paired output
digest, or sanitized replay log in the reviewed directory.  The single summary
digest pins only one document.

A reviewable private replay proof can remain content-free.  Record two output
SHA-256 values, the common source-manifest/edge/cutoff commitments, extractor
digest, interpreter version, return codes, and explicit confirmation that the
two invocations used the same immutable source snapshot.  Do not record paths,
IDs, commands containing secrets, or the HMAC key.

## 8. Counts and claims that may enter the paper

### Usable now, with explicit provenance

The following statements do not depend on treating observational telemetry as
security ground truth:

- Official pinned source shows that the fork filter excludes both forms of
  inter-agent delivery record; copied history representation and a native
  delivery occurrence are different objects.
- The current private snapshot **reports** one 88-file recursive lineage with
  87 selected edges, depth counts 1/85/2, one user-provenance root, 87
  subagent-provenance descendants, and pinned-version counts 36/52.  These are
  one case, not 88 tasks, and should be rounded or selectively reported under
  double blind.
- The declared Claude index **reports** 45 metadata entries and a message-count
  sum of 180; no raw action corpus was recovered; the global filename walk had
  four errors.  This is metadata-only evidence.
- The current v2 JSON's 6,064-call/6,064-result/6,062-strict-pair accounting is
  internally correct, but until rerun it must be introduced only as a
  **provisional current aggregate**, not a final empirical result.

### Eligible after repair and an unchanged two-run replay

If the corrected rerun reproduces them, the exact private-case workload facts
that may be reported are:

- 78 files with inherited prefixes, 219,142 prefix rows excluded, and 39,160
  exact timestamped native/local rows retained;
- 6,064 raw calls, 6,064 raw results, 6,062 strict kind-compatible one-to-one
  pairs, zero duplicate call-ID events, one duplicate result-ID event, and no
  singleton kind mismatch;
- 132 task starts, 114 task completions, 13 aborted turns, 47 compactions plus
  47 compacted records, and one UI rollback record;
- 752 successful patch-completion records with 899 aggregate change entries;
  and
- wrapper-level lexical and result-marker counts, labeled as wrapper syntax
  rather than effects or receipts.

The private case may support only this scientific role:

- one real, longitudinal paper-formation workload used recursive delegation;
- pinned fork logs required provenance-aware normalization;
- ordinary selected telemetry exposed topology, lifecycle, local mutation, and
  wrapper/correlation shapes but no typed record usable by this analysis to
  decide the formal plan/token/effect admission predicate; and
- copied history is not a duplicated authority occurrence or external effect.

It cannot support prevalence, a safety/violation rate, causal benefit from
multi-agent writing, semantic rollback or restore correctness, authority
conservation, discrete-token linearity, exactly-once effects, or validation of
the proposed algorithm.  Formal proof and controlled runtime fault injection
must carry those claims.  Keep the private case, public TraceLab breadth, and
synthetic parser tests as three explicitly separate evidence layers.

## Acceptance gate

Change this verdict to **ACCEPT** only after:

1. each rollout is processed from one immutable byte snapshot, or all passes
   prove identical inode/length/content and use one captured byte limit;
2. the matching header, chosen local `task_started`, and first metadata marker
   are valid exact timestamped rows at or before cutoff, and the spawn marker
   has `trigger_turn is True`;
3. exactly-one-header and source-boundary checks are applied to the same bytes
   that are counted and committed;
4. the HMAC manifest or an immutable DB snapshot covers every
   output-affecting DB field;
5. Claude IDs must be nonempty, scan read errors stay explicit, and the direct
   root-ID command-line form is removed;
6. output privacy validation is path-sensitive over keys and values, and
   digest/model exceptions are field-specific;
7. the real extraction is rerun twice on one fixed source snapshot, leaving a
   sanitized paired-digest replay record; and
8. `summary.json` and `report.md` are regenerated, all existing and independent
   adversarial tests pass, arithmetic is rechecked, and the anonymous artifact
   is scrubbed again.
