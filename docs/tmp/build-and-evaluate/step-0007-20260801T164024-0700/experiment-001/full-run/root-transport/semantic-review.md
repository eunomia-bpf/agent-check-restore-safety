# Independent semantic review: `PlanRootTransport.lean`

Date: 2026-08-01 (America/Vancouver)

Verdict: **PASS for the isolated all-tentative transport bridge**, with the
claim limits below.  This is not a PASS for the full plan-continuity theorem
or for preservation of historical prepared/withdrawn lineage metadata.

Reviewed source SHA-256:
`73a5005cbb7f1054d01e8ff0b9104251aacd7366ead9fb5bb5b46a195bbd59a6`.
This matches `report.md` and `invocation-05.log`.

## Findings

| Question | Result | Reason |
|---|---|---|
| Does `L_target` cover every actual target tentative claim, including non-batch claims? | **PASS** | `tentativeLineageClaims` filters `Finset.univ` by the actual target `status`; there is no batch argument anywhere in `targetCore_tentative_lineage_load_le`.  The proof maps every member of this complete target set into an actual `rho` fiber and then sums all such fibers. |
| Is the target root computed only from the source root and actual `rho`? | **PASS, scoped** | `transportedRoot root tr c'` is definitionally `(tr.rho c').bind root`; the target/canonical theorems and `checkTargetOwnerRootPure` do not accept a second target-root map.  The source `root` itself remains an arbitrary theorem/checker input, however, and the module does not establish that it is the controller's unique authoritative source map. |
| Is the load comparison about the actual target status and demand, without a target-side invariant premise? | **PASS** | The left side is evaluated on `tr.targetCore A allowed`.  Its status is the actual computed `tr.targetStatus A`, and its demand is definitionally `A.auth.demand`.  The only semantic premise is source-side `Transfer.CoreValid A tr`; the proof uses `source_tentative` and `fiber_demand`.  It does not assume target load, target `WF`/`AC`, owner purity, a target envelope, or a proposed target map. |
| Does the owner-purity checker reject one owner spanning distinct scheduled roots? | **PASS** | `checkOwnerRootPure_rejects_distinct_roots` is universal over the two claims, owner, and unequal slots.  It is not merely an example. |
| Does it reject one owner mixing `some s` and `none`? | **PASS** | `checkOwnerRootPure_rejects_some_none` is likewise universal.  The more general `checkOwnerRootPure_rejects_mixed` also covers the reversed `none`/`some` ordering. |
| Does it prove the whole residual envelope or arbitrary-trace plan validity? | **NO (out of scope)** | There is no `E`, `R`, durable baseline, cursor, leaf disposition, or trace invariant in this module.  It supplies only the monotone `L` bridge and an owner-purity checker. |

## Proof audit

For a target tentative `c'`, the actual target-status equivalence yields
`rho c' = some c`; `CoreValid.source_tentative` then establishes that `c` is
an actual source tentative claim.  The equality

```text
transportedRoot root tr c' = root c
```

is derived from that same `rho`, not assumed.  Thus a target claim at lineage
label `r` maps into the source tentative set at exactly `r`.

The load proof then reindexes the superset of target claims by the complete
set of source `rho` fibers.  Since the modeled demand is `Nat`, adding members
outside the target tentative subset is monotone.  Finally,
`CoreValid.fiber_demand` bounds each entire fiber by the corresponding source
claim demand.  No selected promotion batch occurs in this argument.  The
arbitrary `allowed` contract is semantically irrelevant to this particular
status/demand result.

`CoreValid` is a logical record premise rather than a literal Boolean equality
in these theorem signatures.  The repository does prove
`checkTransferCore_sound`, and the canonical wrappers consume
`CanonicalValid.transfer.toCoreValid`; nevertheless, paper wording should say
"under the sound checker certificate" rather than claim that this isolated
theorem itself invokes the Boolean checker.

## Counterexample audit

No counterexample was found to the scoped all-target-tentative theorem.
The requested edge cases behave as follows.

1. **Source root `none`.**  If `rho c' = some c`, source `c` is tentative, and
   `root c = none`, then the target tentative claim has root `none`.  It is
   included in `tentativeLineageLoad ... none`, so it is not silently dropped.
   The scheduled-root specialization intentionally excludes this class.

2. **Source root `some s`.**  Every target tentative descendant with
   `rho c' = some c` receives exactly `some s`, and its demand is charged to
   slot `s`.

3. **Fresh target ID.**  A valid transfer may have `c' != c`, source status
   `c' = unissued`, and `rho c' = some c`.  The target status is tentative;
   its actual preallocated demand `A.auth.demand c'` occurs in both the target
   load and source fiber check, while its root is computed from `root c`.
   Pre-existing root metadata at the fresh ID `c'` is ignored, as required.

4. **Target durable/unissued IDs.**  Under `CoreValid`, durable IDs have
   `rho = none` and remain durable; an unissued ID with `rho = none` remains
   unissued.  Neither enters `tentativeLineageClaims`.  Arbitrary root metadata
   on such IDs therefore cannot contaminate `L` or owner purity.

5. **Historical non-tentative metadata: broader-reading counterexample.**
   Let `root h = some s` and `rho h = none`.  Definitionally,
   `transportedRoot root tr h = none`, including when `h` is a valid durable,
   terminal, unissued, withdrawn, or already-prepared historical ID.  Hence
   this map does **not** preserve lineage metadata for non-tentative history.
   That is harmless for the proved `L` theorem because `L` filters on actual
   tentative status, but a durable ticket or discrete prepared/withdrawn leaf
   ledger cannot recover its historical root from `transportedRoot`.  The full
   design must retain that identity in separate authoritative plan/ticket
   state (or define a different historical map).

6. **Owner-purity totality limit.**  An owner whose tentative claims all have
   root `none` passes purity, because their roots agree.  The checker proves
   non-mixing, not that every tentative claim of a scheduled owner has a
   `some` root.  A separate plan-validity/coverage invariant is necessary.

## Build and axiom audit

- `invocation-01.log` is a retained failed proof-engineering attempt and
  establishes nothing; the later successful evidence supersedes it.
- `invocation-03.log` records successful elaboration and explicit axiom
  output.
- `invocation-04.log` ends with a successful 744-job module build.
- `invocation-05.log` records the matching source hash and
  `FORBIDDEN_SCAN=PASS`.
- I independently re-ran the pinned Lean 4.30.0 single-file command on the
  reviewed hash; it exited successfully.
- Explicit `#print axioms` results contain only `propext`,
  `Classical.choice`, and `Quot.sound`.  There is no `sorryAx`, project axiom,
  `native_decide`, `sorry`, or `admit` in the reviewed source.

## Exact claim limits

The defensible positive claim is:

> For a finite checked transfer, the root map computed from the actual `rho`
> transports every actual target tentative claim, including non-batch and
> `none`-lineage claims, and the total target tentative demand at each lineage
> label is no greater than its source total.  A finite checker soundly rejects
> a target owner that mixes unequal lineage labels.

Do not inflate this to any of the following without additional modules and
integration proofs:

- preservation of root metadata for durable, prepared, terminal, or withdrawn
  historical identities;
- proof that the caller-provided source `root` is authoritative, complete, or
  immutable;
- owner-root assignment totality (purity alone permits all-`none` owners);
- `L + E <= R`, `d = d0 + sum E`, or `B + E + W = P`;
- same-slot Merge admissibility, restriction/Revoke transport, cursor advance,
  Prepare readiness, or arbitrary-trace `PlanValid` preservation;
- physical exactly-once effects or runtime linearizability.

