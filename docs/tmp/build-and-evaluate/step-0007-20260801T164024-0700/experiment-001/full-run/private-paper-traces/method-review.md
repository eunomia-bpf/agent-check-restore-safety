# Independent method review: private paper-formation traces

Date: 2026-08-01 (America/Vancouver)

## Verdict

**REVISE.** The package is useful as a privacy-conscious, formative case study
of one real paper-formation lineage, but it is not yet ready to support exact
paper-facing counts or a double-blind artifact as written.

The existing aggregate is arithmetically self-consistent, and the three
committed synthetic tests pass. The principal blocker is source fidelity: the
native-boundary algorithm is an empirical heuristic whose distinguishing event
can itself occur in copied history. A synthetic counterexample makes it retain
both a copied call and the true native call. Fixed timestamp filtering also
does not freeze malformed or timestamp-less appended rows. These defects do
not prove that the frozen aggregate is wrong, but they make its exact counts
**provisional** until the selected files are validated against a stronger
boundary contract.

There is also a direct double-blind blocker: the extractor contains an
author-identifying username in its default Claude index path. The published
privacy-test claims are broader than the implemented assertions and tests.

## Scope and independence

- Frozen revision: `532cde0025c8916c5487e3f3b0d0f736c9c9db9c`.
- Reviewed only `extract_private_paper_traces.py`, `summary.json`, `report.md`,
  and `test_extract_private_paper_traces.py` at that revision.
- No raw Codex or Claude content was read, no private root ID was obtained, and
  no real extraction was run.
- Existing files were not changed. This review adds only `method-review.md`.
- `FullPlanInvariant.lean` and the subsequent token formalization are outside
  this review.

The cutoff commit `5efc4eaa305ac02d6ac933159ff56c482eea5139` is an ancestor
of the reviewed revision. Its author and committer timestamp is
2026-08-01T20:11:01-07:00, preceding the reviewed method commit at
2026-08-01T20:47:44-07:00. This is useful internal chronological evidence, but
it is not by itself an externally timestamped preregistration.

## Validation performed

The committed test suite and syntax check pass:

```text
python3 -m unittest -v test_extract_private_paper_traces.py
Ran 3 tests in 0.050s — OK

python3 -m py_compile extract_private_paper_traces.py \
  test_extract_private_paper_traces.py
PASS
```

All arithmetic identities directly checkable from `summary.json` pass:

- depth counts and role counts each sum to 88 threads;
- 87 selected edges equal 88 threads minus one selected root;
- top-level event counts sum to 39,160 selected valid rows;
- call-kind, tool, and role totals each sum to 6,064;
- result-kind totals and matched-plus-unmatched totals each sum to 6,064;
- matched-result tool totals, execution-result markers, and every lifecycle
  role decomposition agree with their reported totals; and
- `6064 calls = 6064 matched results + 1 missing result - 1 duplicate result`
  for this sample, where duplicate call IDs are reported as zero.

Three additional synthetic, private-data-free probes exposed boundary cases:

```text
COPIED_METADATA_BOUNDARY
  prefix_rows=0, selected calls=[copied, native]

MISSING_TIMESTAMP_AFTER_CUTOFF
  selected_rows=2, missing_timestamp_rows=1

DUPLICATE_CALL_ACCOUNTING
  call_events=1, custom_call_kind_count=2, duplicate_call_ids=1
```

## 1. Fixed cutoff and lineage selection

**Result: REVISE, not a rejection of the selected case.**

Conditioned on a root and immutable inputs, recursive selection of every
descendant created by the cutoff is preferable to selecting interesting child
rollouts after seeing their contents. The ancestral cutoff commit also excludes
ordinary post-cutoff events that carry valid timestamps.

It does not fully rule out post-hoc selection:

1. The root ID is supplied at runtime and has no committed, privacy-preserving
   commitment or deterministic repository-to-root selection rule. The method
   therefore cannot show that the root was fixed before metrics were examined.
2. A Git committer timestamp documents an internal cut but is author-controlled;
   the package contains no signed/external timestamp or preregistration record.
3. The live SQLite query filters child `created_at`, but spawn edges have no
   event-time filter or frozen DB snapshot. A later edge linking pre-cutoff
   records could change the selected topology.
4. The content digest freezes only the observed multiset of selected rollout
   bytes. It does not freeze the DB rows, root identity, edge mapping, file byte
   limits, or source schema.
5. Valid rows with absent/unparseable timestamps are selected even after a
   known future row (`extract_private_paper_traces.py:369-388`). Malformed
   appended rows can also be selected depending on the preceding row. Thus a
   timestamp cutoff alone does not make a live append-only source immutable.

For an exact-count claim, commit before analysis a redacted selection manifest:
full cutoff object, selection rule, salted/HMAC commitment to the root ID,
runtime/schema versions, lineage edge digest, and per-rollout byte length or
content digest. Alternatively take a read-only snapshot and hash it. If this
was chosen retrospectively, say **retrospective fixed-cutoff case study**, not
preregistered or selection-bias-free.

## 2. Structural native boundary and tests

**Result: blocker for exact counts.**

For a child, the extractor chooses the last `task_started` preceding the first
`inter_agent_communication_metadata` in the entire file
(`extract_private_paper_traces.py:303-340`). This works for the committed
positive fixture. It fails if copied parent history already contains an
inter-agent metadata event: the scan stops inside copied history and counts the
copied suffix as native. This is a plausible fork-history shape and must be
distinguished by a source-native provenance field, recorded copied-prefix byte
length, or a validated unique state-machine boundary—not merely by changing
“first” to “last.” Ambiguous files should be quarantined rather than guessed.

The implementation records only whether at least one matching local header was
found. It does not count matching headers, so `report.md:62` cannot claim
“exactly one” per file. Likewise, the report says the three tests cover multiple
copied headers, full arithmetic invariants, determinism, and a privacy denylist
(`report.md:250-269`), but the test file contains only:

- one copied-prefix positive case;
- one no-history/invalid-row cutoff case; and
- one missing-result/duplicate-result aggregate case.

Required additions include copied prefixes with earlier inter-agent metadata;
zero/multiple candidate triggers; multiple matching and copied headers;
multiple `task_started` events; missing, malformed, future, and out-of-order
timestamps; duplicate/non-string call IDs; mismatched call/result kinds;
multi-parent/cyclic lineage rejection; deterministic replay from a frozen
fixture; and assertions over the complete emitted-value allowlist.

## 3. Counting semantics

**Result: current summary PASS; generic implementation REVISE.**

The frozen aggregate's published arithmetic is correct under its reported
zero-duplicate-call-ID condition. The report also correctly explains why equal
call/result totals do not imply one-to-one matching.

However, `call_events` is computed as `len(part["calls"])`, where `calls` is a
dictionary keyed by call ID (`extract_private_paper_traces.py:422-425,511`). A
duplicate call overwrites its predecessor, so `call_events` becomes a unique-ID
count while `call_kind_counts` remains an event count. The adversarial fixture
reports one `call_events` but two custom-call events. Report separate
`raw_call_events`, `calls_with_string_id`, and `unique_call_ids`; do not rely on
an equality that holds only for the current sample. Also require call/result
kind compatibility before calling an ID match protocol-correct.

The selected edge identity `edges = nodes - 1` is consistent with a tree in
this sample, but the recursive `UNION ALL` query has no explicit uniqueness,
single-parent, or cycle guard. Assert those properties rather than infer them
from the final count.

## 4. Privacy and data governance

**Result: good minimization principles, but REVISE before distribution.**

Positive properties include read-only SQLite mode, no raw trace rows in the
aggregate, enum normalization for most event fields, within-thread ID joins,
and explicit interpretive limits.

Release blockers and residual risks are:

- `extract_private_paper_traces.py:844` embeds `yunwei37` in a default path,
  directly defeating double blindness.
- `privacy_assertions` checks emitted values only for the supplied root ID, the
  current home path, and UUID-shaped strings (`:804-828`). It does not implement
  the report's claimed denylist for prompts, commands, code, credentials,
  result bodies, patch paths, remote names, or every child/session ID.
- Model names shorter than 40 characters are copied from the private DB rather
  than allowlisted (`:493-498`). This is an unbounded string-valued leak path.
- Claude IDs are passed to `rg` as process arguments (`:643-660`), making them
  visible to local process inspection while the scan runs.
- Exact dates, a repository commit hash, model label, and a distinctive count
  vector can fingerprint the authors or link an anonymous artifact to a public
  repository. The full-home Claude scan also exceeds the minimum target-store
  scope and needs explicit authorization and retention policy.

Make the Claude index an explicit argument with no identifying default;
allowlist every output string; pass sensitive search terms through protected
stdin/in-process matching; test both output values and the distributable
artifact; and publish rounded/relative dates or an anonymous-repository commit
only. Preserve raw data privately with access, retention, and deletion rules.

## 5. Claims the evidence can and cannot support

After source-fidelity repair, the private case can support:

- one author-operated paper task contained one recursive parent/child lineage
  with the reported aggregate topology and telemetry shapes;
- this captured runtime format copied parent history into many child logs and
  therefore required provenance-aware normalization;
- ordinary telemetry in this case exposed controller topology, workspace
  activity markers, and outward-looking **wrapper syntax**, while lacking
  enough typed evidence to decide the paper's formal admission predicate; and
- call/result correlation, compaction, UI rollback, and lexical wrapper markers
  are not equivalent to effect tickets, semantic Restore, or durable receipts.

It cannot support prevalence, 88 independent tasks, causal benefit from
multi-agent orchestration, a safety/violation rate, rollback correctness,
authority conservation, exactly-once effects, or validation of the proposed
algorithm. Repository commits in the same wall-clock window are artifact
activity, not outcomes causally joined to the selected lineage.

The statement that the *schema* lacks every required authority/effect field is
also stronger than this extractor establishes: it counts selected event types
but does not emit or mechanically audit all field keys. Say that the selected
telemetry exposes no typed record usable by this analysis, or add a pinned
schema/field-presence audit. Likewise, the case **illustrates** extra-workspace
state and an observability gap; without an actual checkpoint/restore pair it
does not demonstrate that a particular workspace restoration lost that state.

## 6. Self-hosted case versus public TraceLab

Keep three evidence layers separate:

| Evidence | Proper role | Must not be used for |
|---|---|---|
| Private self-hosted lineage | Longitudinal mechanism case; fork-log format; instrumentation-gap discovery; motivating workload shape | Population estimates, independent validation, safety efficacy, or causal claims |
| Public TraceLab | Externally reproducible breadth for generic tool/error/continuation and schema observations, subject to its own pinned audit | Semantic Fork/Restore lineage, authority ownership, effect tickets, or crash-relative ground truth |
| Synthetic fixtures | Parser correctness and adversarial regression tests | Ecological prevalence or runtime safety evidence |

The formal model and controlled fault-injection/runtime experiments—not either
observational corpus—must carry the security and algorithm-correctness claims.
TraceLab numbers cited in `report.md` were not revalidated in this deliberately
private-directory-only review and need their own source-pinned citation.

## 7. Double-blind CSF reporting

The case can be reported in a double-blind CSF submission **after revision** as
“one author-operated, non-public longitudinal case study.” State that raw traces
cannot be released, that external reviewers can reproduce only the public and
synthetic portions, and that private aggregate counts are author-auditable but
not independently reproducible. Include an ethics/data statement covering
ownership or consent, incidental third-party/private content, minimization,
access, retention, and release policy.

Before submission, remove the identifying default path and scrub Git history,
absolute paths, exact timestamps/hashes linked to public identities, usernames,
remote names, and any distinctive internal runtime label from the anonymous
artifact. Do not call the current package “reproducible” without qualifying
which layers a reviewer can actually rerun.

## Acceptance gate

Change the verdict to **ACCEPT** only after:

1. the native-boundary contract is strengthened and every selected file is
   unambiguously validated or excluded;
2. root/cutoff/lineage and source-byte selection are frozen in a redacted
   manifest, with retrospective selection labeled honestly;
3. timestamp-less and malformed append behavior is made deterministic;
4. counting labels and lineage integrity checks are corrected;
5. the missing adversarial, determinism, arithmetic, and privacy tests exist;
6. the extractor and artifact pass a double-blind/privacy scrub; and
7. paper claims are narrowed to the three-layer evidence division above.

