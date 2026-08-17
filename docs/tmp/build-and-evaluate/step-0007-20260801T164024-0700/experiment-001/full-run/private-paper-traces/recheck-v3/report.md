# Final independent recheck of the private paper-trace v3 method

Date: 2026-08-01 (America/Vancouver)

## Verdict

**ACCEPT, for the explicitly scoped retrospective single-case trace role.**

All eight gates from the preceding independent reviews are now closed.  The
23 maintained tests, 16 prior independent attacks, and 21 fresh v3 attacks all
pass: **60/60**.  The current extractor digest is exactly the one recorded by
the replay evidence; both recorded replay output digests equal each other and
the current `summary.json`; all three recorded commitment-equality checks are
true; and the main method report states the final digest.

The accepted claim is deliberately narrow: the package can describe the
workload and ordinary telemetry of one author-operated paper-formation
lineage, under the pinned Codex source contract and private-input boundary.  It
does not validate the paper's safety algorithm, estimate prevalence, identify
unsafe restores, prove authority conservation, or establish exactly-once
external effects.

No private rollout, root/key file, Claude raw path, prompt, command, result,
or stable private identifier was opened or used by this review.  The review
read only the extractor, aggregate, replay record, reports, paper wording, and
synthetic tests.  It wrote only `recheck-v3/`.

## Final reviewed pins

```text
extractor         38e7b7ec39b78ab9299277b9fec545a65450b77975b499f7856afa641e7756a4
maintained tests  3a48c3b027a0d75c95ab8023f64833f46411e3f1a8de00de4a3dc7fe52687401
prior attacks     19fa71c827c3c792be8aee0d0166cecf17259340b28db5f6e04979a06cd457e0
fresh v3 attacks  0c58cf4142f81cad4622e5f61d257ad74fe6f8587bed0f18ea5047c8d71691bb
summary           ae4d362b7f4ccc0ae2dedaca703bccc3d9b47fc7b9e8ca40301415040f5ad5a7
main report       abf6891d95197680c4287d37875c08fadf9c8008905f0897fcc1105d265adfa1
replay evidence   2ad4833902c726b9c3f8fb52ef84a3d20070828cdb8cf29ace3c5b2f7049e4e4
validation.tex    84987ecad7ab1c507c5f2d4a4046254b41bea4481c02971f0627daeab09e1dd0
```

These pins are for this final judgment.  The exact private summary, its digest,
and this pin-bearing report can fingerprint the case and should be withheld
from the anonymous artifact together with the HMAC values and key.

## Gate-by-gate result

| Acceptance gate | Final result | Independent evidence |
|---|---|---|
| One immutable rollout byte image | **PASS** | Same-size byte overwrite and identical-byte/same-size inode replacement both fail closed. |
| Exact boundary, physical cutoff, strict trigger | **PASS** | Header/task/marker timestamps and order are checked on the captured bytes; false, integer, string, and null trigger values reject; backdated suffix rows cannot cross a future stop. |
| Counting and commitment use the same bytes | **PASS** | Boundary discovery, counting, prefix hashing, and selected hashing consume the same `snapshot_lines`. |
| Coherent lineage and committed selected DB inputs | **PASS** | One explicit read-only SQLite transaction covers schema/edge/thread reads; duplicate, cyclic, multi-parent, missing-child, and missing external-root-parent cases reject; selected provenance fields and edge status affect commitments. |
| Canonical Claude IDs and explicit scan uncertainty | **PASS** | Empty/noncanonical IDs reject; canonical synthetic IDs accept; yielded-file, targeted-directory, global-walk, project-index parse, and project-index enumeration errors are surfaced. |
| Complete-path privacy validation | **PASS** | Keys, fixed string values, timestamps, and SHA-256 fields are tied to their complete schema paths; scalar types/ranges and dynamic counter keys are checked; UUID/path/free-string denial remains separate defense in depth. |
| Private paired replay evidence | **PASS** | Two serial invocations returned zero; their output digests are identical; the final summary bytes have that digest; extractor and commitment-equality pins agree. |
| Regenerated reports and all attacks | **PASS** | Syntax/import checks pass and all 60 tests finish successfully; the main report and paper retain scoped wording. |

## Closed findings from the prior REVISE verdict

### Complete-path output schema

The prior validator used global allowlists.  The repaired
`_privacy_output_schema` now maps each complete document path to a container or
scalar validator.  A root-level `threads`, a provenance label in
`schema_version`, and a root HMAC field under `claude` all reject, while the
same digest at `codex.lineage.root_hmac_sha256` accepts.  Counter maps restrict
their dynamic labels, integers reject Boolean substitution, nonnegative fields
reject negative values, and fixed strings are field-specific enums.

The schema intentionally permits synthetic tests to validate a sparse subtree;
every field that is present must nevertheless occur at its exact path.  The
production call validates the complete generated document.  This is adequate
for the stated privacy/output-regression role; it is not a separate wire
protocol with mandatory-field or cross-field semantic rules.

### External-root parent endpoint

`read_lineage` now resolves the unique external parent of a selected root in
the same SQLite read transaction.  A missing endpoint fails closed before the
edge commitment is returned.  Both the maintained regression and the original
fresh attack pass.  A valid externally parented selected root remains
normalized as a subagent and its incoming edge remains committed.

### Targeted and project-index traversal errors

`_iter_regular_files` now accepts an error callback, performs explicit `lstat`
checks, passes `onerror` into `os.walk`, and propagates traversal/open errors
into `reference_scan_read_errors`.  Project-index discovery uses guarded
`os.scandir` and exposes `project_index_walk_errors`; parse errors remain
separate.  Both the maintained and fresh injected-error fixtures pass.

The real aggregate reports zero targeted traversal/open/read errors and zero
project-index enumeration errors.  Its global filename walk still reports four
errors, so the report correctly describes only the traversed portion and makes
no global absence claim.

## Source and snapshot contract

The official pinned 0.145 and 0.146 sources were independently rechecked.  In
both, full-history fork filtering removes `InterAgentCommunication` and
`InterAgentCommunicationMetadata`; v2 tool communication is constructed with
`trigger_turn=true`; and a regular task emits `TurnStarted` before running turn
input.  This supports using the first valid local delivery marker, under the
validated legacy/v2 header contract, to distinguish copied prefix from native
child execution.

The implementation accepts only the two pinned versions and matching legacy
history, validates local structured provenance and DB parentage, and requires
one exact matching local header.  Version/header fields are compatibility
evidence, not cryptographic attestation that an official binary generated
uncorrupted bytes.

Each rollout is captured through one regular, nonsymlink file descriptor.  The
extractor compares device, inode, size, modification time, and change time
before and after the exact-size read and checks the path identity.  All parser
passes use the captured byte array.  The fresh suite proves detection of both
same-length in-place modification and identical-content path replacement.

This is an ordinary trusted-local-filesystem snapshot boundary, not a hostile
storage proof.  EOF commitments cannot prove when a backdated append was
created.  No immutable SQLite image or external timestamp was retained, and
spawn edges themselves have no event timestamp.  The HMACs are private
integrity commitments, not public preselection proofs.

## Aggregate and replay consistency

Two independent arithmetic checkers pass the published summary.  They cover
the lineage/tree identities, depth/role/model/effort partitions,
header/version and EOF/future-stop partitions, exact top-level row sum, raw
call/result and ID partitions, strict-pair complements, tool totals, execution
marker totals, and lifecycle role totals.

The final replay record states two zero return codes and two identical output
digests.  That digest is exactly the current summary's byte digest, and the
record pins the current extractor.  Source-manifest, edge, and cutoff
commitment equality flags are all true.  The aggregate's exact scientific
counts remain unchanged by the final integrity repairs.

During the first final recheck, a background paired extraction and evidence
update completed out of order, so the reviewer observed a summary/evidence
digest mismatch and withheld acceptance.  The final runner explicitly waited
for both extraction processes to exit before installing the summary and
evidence.  The reviewer then reran all 60 tests against the final pins above;
the digest-equality attack passed.  This packaging incident is resolved and is
not silently omitted from the audit history.

## Report and paper claim audit

The main report now makes the correct narrow claims:

- this is one retrospective author-operated lineage, not 88 independent tasks
  or a sampled population;
- copied-history normalization is admitted only for the pinned legacy/v2
  source contract;
- the analyzed records exposed topology, lifecycle, local patch/wrapper, and
  call/result shapes but did not jointly expose the typed fields needed by the
  formal admission predicate;
- Claude contributes declared-index lifecycle metadata only, with no action or
  effect counts; and
- observational traces do not establish safety, causality, authority
  conservation, or exactly-once execution.

The paper's `validation.tex` is aligned with that scope.  It says traces
“characterize observed workload shapes,” treats the trajectory as one
self-hosted longitudinal dataset and retrospective case, uses rounded counts,
describes “aborted turns and subsequent task-lifecycle records” rather than a
typed recovery relation, and says the analyzed records “did not jointly
expose” the admission fields.  Its “bounded exact-ID recovery” wording does not
claim exhaustive absence, and it assigns Claude no tool/effect count.

The privacy paragraph also matches the artifact boundary: only analyzing
authors access raw logs/key; the private summary, commitments, and raw data are
withheld; paper-facing counts are rounded; and only code, public analysis, and
synthetic fixtures are intended for anonymous release.

## Claims admitted by this ACCEPT verdict

The private case may support only the following descriptive statements:

- one real paper-formation task used a recursive Codex delegation lineage;
- it contains more than 80 rollout files over two delegation depths, roughly
  39,000 timestamped native/local rows, roughly 6,000 calls, and more than
  200,000 excluded inherited rows;
- pinned full-history logs require provenance-aware copied-prefix
  normalization;
- ordinary telemetry exposes useful topology, lifecycle, patch-completion,
  wrapper, and call/result-correlation shapes; and
- the analyzed fields do not jointly implement the proposed plan/token/effect
  admission record.

The exact aggregate can remain in the private audit but the anonymous paper
should retain rounded/selective counts.

## Claims still excluded

This ACCEPT verdict does not support:

- prevalence across users, projects, agents, or independent tasks;
- an unsafe-restore, duplicate-effect, retry, or rollback-safety rate;
- semantic checkpoint/restore or interpretation of the one UI rollback marker
  as Restore;
- authority conservation, token linearity, plan validity, or exactly-once
  effects;
- causal benefit from multi-agent paper writing;
- product-wide absence of richer unexamined telemetry; or
- equivalence between this Codex case, Claude metadata, and public TraceLab.

Formal mechanization and controlled runtime fault injection must continue to
carry the security and algorithm-correctness claims.  Within this boundary,
the private v3 trace method is independently accepted.
