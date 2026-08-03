# Error retrospective: CSF paper evolution, review validity, and freeze choice

Generated: 2026-08-03 06:33:54 UTC

## 1. Decision and scope

Decision: should the current CSF paper be rolled back because it became weaker or
narrower, and what workflow change would prevent another invalid review-driven
rewrite?

This is an analysis-only retrospective. The only allowed write is this report.
The following are frozen:

- `docs/paper/` and all scientific claims;
- shared and repository-local skills;
- the existing Git history and review artifacts.

No skill promotion experiment was requested or run. The candidate process changes
below therefore have verdict `propose`, not `promote`.

## 2. Source coverage and validity gates

### Source manifest

| Source | Discovery and coverage | Identity and lineage | Parse/coverage result |
|---|---|---|---|
| Codex session archive | Literal repository-path search over `/home/will/.codex/sessions/2026/08/02/` and `/home/will/.codex/sessions/2026/08/03/` | Source-native `payload.id`, filename ID, `session_id`, `forked_from_id`, `thread_source`, and `source.subagent.thread_spawn` | 71 JSONL archives, 110,583 timestamped records, 71/71 syntactically valid; event range 2026-08-02 20:09:10Z through 2026-08-03 06:35:39Z |
| Interactive-parent stratum | `thread_source == user` | Three source-native archives; the main continuing task is rooted at session `019fc423-1fe2-7593-8acf-2a9741e9ea11`, forked from `019fc418-1fd1-72c2-8ada-ecf1a8da7468` | 3 archives; kept separate from children |
| Delegated-agent stratum | `thread_source == subagent` | 68 unique archive IDs; 63 depth-1, 4 depth-2, and 1 depth-3 tasks | Lineage retained; children are trials within one parent task, not 68 independent projects |
| Git repository | `git log`, commit inspection, and `git rev-parse <commit>:docs/paper` | Commit hash and `docs/paper` tree hash | Current HEAD/origin is `893598b`; clean before this report. Among `f91de59` through `893598b`, nine commits contain only six distinct paper trees |
| User constraints | Parent transcript and `docs/user-instruction.md` | Chronological user turns | Direct evidence for Agent centrality, no self-downgrade, four fresh reviewers after each edit, and the later “do not make big changes” constraint |
| Artifact/checker evidence | LaTeX build, focused/full tests, citation, structure, terminology, and language gates reported in the same task | Checker kind and repository state | Useful for compilation and local consistency only; excluded from CSF accept/reject counts |

The six distinct paper trees in the post-phase1 rewrite chain are:

| Commits | `docs/paper` tree |
|---|---|
| `f91de59`, `e4bedc3` | `f2fddd12462877209cecce7ddcf6e68b50abc7e5` |
| `5244e9c`, `c14bd95` | `c2baddbacf40a003882c8f2d10fb4292a63e3e93` |
| `c460a55`, `c740ad7` | `cada612dc07d63c025fcefa329a794f861191dfa` |
| `0a43578` | `3ee865b8ef1587af51a832ad41b7df913ee452fc` |
| `d684302` | `dc1187533a534c411685aa89c3114e2b8929e7ca` |
| `893598b` | `3d2b75c1bf48acc015d4c473a7a70d39a7b1605e` |

### Validity gates

- **Session identity: pass.** Discovered-file count and unique archive ID count
  are both 71. Parent/child metadata is present.
- **Lineage: pass for the decision-critical review rounds.** The audit distinguishes
  direct depth-1 reviewers from reviewers spawned under specialty-gate agents.
- **Raw parsing: pass.** All 71 archives parse as JSONL.
- **Reviewer-outcome independence: partial/stratum blocker.** Directed reviewers,
  same-reviewer revision checks, and specialty gates are not independent holistic
  venue reviews. They are excluded from CSF recommendation aggregates.
- **Cross-version comparison: provisional.** Reviewer pools and prompts changed
  across revisions. Their verdicts can identify recurring objections, but cannot
  establish that one edit caused a score change.
- **External outcome: unavailable.** All reviewer verdicts are model reports within
  one parent research task; there is no real CSF decision. No promotion or causal
  quality claim can be supported.

Known blind spots: ephemeral, uncommitted intermediate PDFs cannot all be
reconstructed from Git; no externally signed review forms exist; and the archive
does not turn multiple children of one parent task into independent research
projects. These gaps do not block the narrow conclusions about review aggregation,
Git-version identity, or whether an old commit should replace the current one.

## 3. Workload strata

1. **Human-interactive parents:** the user and root agent chose scope, authorized
   rewrites, interpreted reviews, and decided when to freeze.
2. **Delegated authors/researchers:** children proposed theory or edited sections.
   Their outputs are design evidence, not review verdicts.
3. **Holistic CSF reviewers:** children asked to review the whole frozen paper.
   Only fresh, non-directed reviewers count toward a venue-style recommendation.
4. **Specialty reviewers/checkers:** structure, style, terminology, novelty, and
   clarity gates. They diagnose their assigned dimension and never count as a
   holistic Weak Accept.
5. **Executable/checker workloads:** compilation, tests, citation verification,
   page/metadata/font checks, and artifact fixtures. These validate stated
   properties only.

No benchmark/replay traffic was used to infer human correction rates. No lexical
correction heuristic or token/cost metric was used.

## 4. What actually happened to the paper

| Paper state | Main move | What improved | What regressed or remained exposed |
|---|---|---|---|
| `f91de59` phase1 | Exact evidence over endpoint families, identity quotients, controller cover, and co-liveness lower bounds | Strong “exact theory” posture and substantial artifact support | Thirteen-result component pile; unordered endpoints lose causal order; Agent is not the title/theoretical center; runtime realization remains external |
| `5244e9c` | Exact monitor/controller substitution | Makes monitor compilation explicit | Genuine scope/novelty downgrade: the sandwich result is close to definitional, causality is still absent, and deployment facts remain external |
| `c460a55` | Canonical causal epochs | Adds sequence/choice/parallel causality, online composition, and install races | The request can supply promises/source/anchors, permitting obligation understatement; occurrence/cell and pointwise-liveness defects remain |
| `0a43578` | Exact Agent history realization | Trusted Agent DAG, checkpoints, occurrences/cells/owners, six edits, Fresh/Alias, and durable execution; Agent no longer supplies the target | Root-only per-outcome existence can accept a shared prefix that later strands another still-compatible outcome |
| `d684302` | Prefix-robust security compiler | Repairs the preceding semantic flaw with an outcome-indexed greatest fixed point; unifies schema fidelity, exact existence, greatest realization, ranked rejection, and durable weak bisimulation | Prior-work boundary and independent realization definition are underdeveloped; Save and handle handoff are incomplete |
| `893598b` current | Formal strengthening and honest generalized-nonblocking correspondence | Adds independent exact-realization semantics, explicit Save, typed handles/gates/bundles, handoff conditions, and a clearer proof boundary | Wording makes the known decision kernel more salient than the novel end-to-end derivation/realization boundary; schema lifecycle, hidden observations, and atomic-domain assumptions remain review targets |

### Scope finding

The current paper did **not** monotonically shrink. Relative to `0a43578`, its
security property is strictly stronger: every admitted prefix must preserve a
safe completion for every outcome still compatible with that prefix. All six
operations, arbitrary successive admitted edits, irreversible receipts,
Fresh/Alias, canonical monitoring, and durable epoch realization remain.

There was one explicit **scope substitution** relative to phase1:

- removed from the center: arbitrary distributed controller covers, controller
  identity exactness, co-liveness arity lower bounds, and decentralized topology;
- added to the center: authenticated Agent-history semantics, causal outcomes,
  prefix-robust realization, receipt-sensitive identity, and durable execution
  across edits.

There is also a real architecture restriction: one atomic epoch per policy domain,
with independent domains composed by product and no claim of within-domain partial
fencing. This restriction is public, not a hidden recent shrink.

### Novelty finding

The technical theorem did not become smaller between `d684302` and `893598b`.
What became smaller was the **perceived novelty posture**. The current paper
correctly concedes that, after outcome-compatible markings have somehow been
supplied, the fixed-point decision phase corresponds to conditional/generalized
nonblocking. It does not yet separate with equal force the work on either side:

1. deriving the markings and non-discardable obligations from authenticated Agent
   history, registered edit semantics, occurrence/cell identity, and receipts; and
2. realizing the result as a durable history cut with a canonical monitor and
   epoch transition.

This permits the reductive reading “known nonblocking plus trusted encoding plus
atomic fencing,” even though the end-to-end scientific object is broader.

## 5. Review-result reconstruction

The remembered “almost all Weak Accept” signal has a real source, but it was not
a valid four-reviewer blind round:

| Paper/review state | Reviewer lineage and task | Result | Valid use |
|---|---|---|---|
| Phase1/`58c5fa5` | Same reviewer after revision | WA | Revision feedback only; not fresh |
| `58c5fa5` | Two directed novelty/clarity reviewers | WA, WA | Specialty evidence only |
| `58c5fa5` | Four fresh, non-directed reviewers | **1 WA, 3 WR** | Comparable holistic round |
| `bcda057` | Four fresh reviewers | **4 WR** | Comparable holistic round |
| `5244e9c` | Four fresh reviewers | WR, two MR/lean-reject, Reject | Comparable holistic round |
| `c460a55` | Four fresh reviewers | 3 Reject, 1 MR | Comparable holistic round |
| `0a43578` | Four fresh reviewers | 1 WR, 3 Reject | Comparable holistic round |
| `d684302` | Three specialty gates plus one holistic review | Structure Pass; style Pass; terminology Needs Revision; holistic WR | Only the final WR is a holistic recommendation |
| `893598b` | Four fresh holistic reviewers with the requested neutral CSF prompt | **4/4 MR or WR** | Current valid holistic round |

Thus two distinct aggregation errors occurred inside this one parent task:

1. three sequential favorable results at `58c5fa5` were remembered as a near-
   consensus even though they were a same-reviewer recheck plus two directed
   reviews; the subsequent fresh round was 1 WA / 3 WR;
2. at `d684302`, structure/style/terminology gates were treated as though they
   were three favorable venue votes, despite there being only one holistic CSF
   recommendation, which was WR.

Repository strings such as `ACCEPT for execution`, experimental `ACCEPT`, or the
paper's `Accept/Reject` admission API are unrelated to venue acceptance and were
excluded.

## 6. Failure clusters

### A. `metric_invalidity` with secondary `review_priming`

**Direct observation:** two review-aggregation errors in one parent task, as
described above. In both, task type and lineage were discarded when summarizing
the apparent vote.

**Impact:** the root agent told the user that a version had nearly all favorable
reviews and used that impression to reason about rollback. That statement was not
supported by a comparable holistic-review denominator.

**Owner:** review/orchestration procedure, not sentence-level writing skills.

**Alternative explanation:** specialty reviews were still useful diagnostic
evidence. The error was counting them as venue recommendations, not running them.

### B. `concept_churn` with secondary `premature_downstream_work`

**Direct observation:** the nine commits from `f91de59` through `893598b` encode
six distinct paper trees and at least five changes of central abstraction:
endpoint evidence, monitor substitution, causal epochs, exact history realization,
and prefix-robust compilation. This occurred within roughly one overnight parent
task, while full-paper prose, formatting, and review cycles proceeded after each
major shift.

**Impact:** downstream writing and checker success repeatedly became stale; each
new review could trigger another scientific-contract rewrite.

**Owner:** root scientific decision/freeze gate. This is not evidence that
`paper-writing-style` or terminology checking caused the churn.

**Alternative explanation:** several changes were necessary repairs, especially
removing caller-controlled promises and strengthening root-only liveness to
prefix robustness. Churn count alone does not imply that the resulting theory is
worse.

### C. `checker_theater` with secondary `outcome_blindness`

**Direct observation:** many compilation, style, terminology, structure, and
fresh-review checks were performed, but their outcomes were sometimes collapsed
into a generic readiness impression. Re-running checks did not resolve the main
novelty boundary identified by holistic reviewers.

**Impact:** local pass signals obscured the distinction between “internally
consistent and compilable” and “convincing CSF contribution.”

**Owner:** review-result synthesis.

**Alternative explanation:** the checks did catch real errors and should remain;
only their interpretation needs correction.

### D. `correction_churn`

**Direct observation:** the parent trajectory contains repeated user corrections
that Agent must remain central, callers must never self-downgrade obligations, the
paper needs one unified theory rather than a component composition, scope must not
silently shrink, and the latest round must avoid a large rewrite.

**Impact:** these constraints were not held as a stable scientific contract
before several rewrites.

**Owner:** root task memory and change authorization.

No global correction rate is reported because no correction heuristic was
calibrated; this is a qualitative finding from one parent task.

### E. `source_fidelity` risk avoided during this audit

**Direct observation:** three pairs of commits have identical `docs/paper` tree
hashes. Counting all nine commits as nine independent paper revisions would be
wrong.

**Impact avoided:** the retrospective uses six paper trees, not commit count, for
the paper-evolution denominator.

## 7. Ranked candidate process changes

These are proposals for a project-local paper-review procedure. No skill file is
changed.

### 1. Preserve reviewer lineage and task type in every verdict

For each review, record the PDF hash or paper commit, reviewer archive/session ID,
depth, exact prompt class, holistic versus specialty scope, fresh versus reused
lineage, and explicit recommendation. A venue-vote summary may include only fresh
holistic reviewers from the same frozen artifact. Report the complete round, not
an interim favorable prefix.

Expected value: high. Risk: low. Specialty gates remain available, but are labeled
as diagnostics.

### 2. Freeze a change budget before editing a reviewed paper

Record the baseline commit, allowed claims/definitions/files, and rollback point.
When the user says “do not make big changes,” novelty-language repair cannot
silently become another theorem rewrite. A scientific-contract rewrite should be
separately authorized after a concrete unsoundness argument or a repeated
theorem-level objection from comparable holistic reviews.

Expected value: high. Risk: medium, because an overly rigid rule could delay a
necessary correction. The exception for concrete unsoundness is essential.

### 3. Compare paper states on separate axes

Before recommending restore/rollback, compare:

- scientific object and operations;
- strength of the security property;
- implementation/architecture restrictions;
- novelty language;
- proof/artifact completeness.

Also compare `docs/paper` tree hashes, not commit labels. This prevents a stronger
theorem with weaker prose from being mislabeled as a wholesale scope regression.

Expected value: medium-high. Risk: low.

### 4. Keep writing skills frozen

`paper-writing-style`, structure, terminology/info-flow, and citation checking
should continue to own their local gates. The observed failure is upstream review
aggregation and scientific-contract churn; adding more guards to writing skills
would be skill bloat and would not change the bad decision.

Expected value: medium. Risk: low.

## 8. Current freeze recommendation

Do not restore phase1, `5244e9c`, `c460a55`, `0a43578`, or `d684302` wholesale.
Use `893598b` as the technical baseline and `d684302` only as a narrative
comparison point:

- phase1 restores attractive exact-theory language but also restores the
  component pile and unordered endpoint abstraction;
- `c460a55` restores caller-controlled promise understatement;
- `0a43578` restores the shared-prefix liveness flaw;
- `d684302` restores stronger contribution posture but loses formal repairs now
  present in `893598b`.

The safe next change, if separately authorized, is a bounded narrative repair:
make generalized nonblocking the internal decision kernel *after* this theory has
derived authenticated Agent-specific obligations, and state explicitly what
generalized nonblocking alone cannot supply. Preserve the current theorem,
operations, scope restrictions, and proof repairs.

The current paper itself was not modified in this audit.

## 9. Verdict, uncertainty, validation, and rollback

**Verdict: `propose`.**

The review-lineage and aggregation failure is directly supported within this
parent task. It justifies a project-local procedure proposal, not a global shared
skill change: all examples share one repository, one user task, and related prompt
lineage. No baseline/candidate comparison or held-out evaluation has established
causal improvement.

Remaining uncertainty:

- model reviewer recommendations are noisy and not real CSF outcomes;
- not every uncommitted intermediate PDF is reconstructable;
- the present 4/4 WR round may reflect reviewer sampling as well as paper issues;
- the audit supports “current technical scope did not shrink” but cannot predict
  acceptance without an external submission.

Validation performed:

- 71/71 discovered session archives parsed;
- parent/child depth and reviewer lineage were preserved;
- relevant review pools were manually classified by prompt scope;
- nine post-phase1 commits were reduced to six paper trees by Git hash;
- current HEAD and origin were both `893598b` before this report;
- no paper or skill file was changed.

Rollback trigger for any later process patch: roll it back if it suppresses
specialty diagnostics, permits mixed-artifact vote aggregation, or blocks an
authorized correctness repair without an explicit exception. Because this report
is additive and contains no active workflow code, deleting it is the complete
rollback.

Files changed by this retrospective:

- `analysis/2026-08-03-063354-paper-freeze-review-error-retrospective.md`

