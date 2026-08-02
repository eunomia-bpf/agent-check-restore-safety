# Claim-oriented novelty audit: clone-plan synthesis

**Date:** 2026-08-02
**Objective:** Decide whether a theory-guided tool for transporting agent state
through Fork/Restore/Merge has a defensible claim beyond capability systems,
rollback protection, clone policies, and supervisory control.

## Claims audited

1. “Authorization continuity” is a new property.
2. Epoch-bound capabilities and version gates are a new enforcement mechanism.
3. A per-component `Copy/Share/Split/Persist/Revalidate/Reject` plan is new.
4. A compiler can synthesize, rather than merely check, the semantic state
   transformation required by a typed history operation.
5. The compiler can safely reuse an old lease through a proved refinement
   instead of uniformly invalidating it.

## Search and primary sources inspected

- exact/near-exact searches for agent authorization continuity, evolving-agent
  authority ceilings, coding-agent capabilities, clone sharing policies,
  Fork/Restore authority, and most-permissive controller synthesis;
- [*Are You Still the Agent I Authorized?*](https://arxiv.org/abs/2607.23586),
  including its model, mutation classes, guarantees, limitations, and claimed
  contributions;
- [*Lingering Authority* / PORTICO](https://arxiv.org/abs/2606.22504),
  including contract compilation, closure predicates, epochs, guarantees,
  evaluation, limitations, and excluded optimal compilation;
- [Plan 9 system manual](https://9p.io/sys/doc/9.html), especially `rfork`'s
  per-resource share/copy/new flags;
- [*Secure the Clones*](https://lmcs.episciences.org/801), including its
  maximum-sharing copy policy, static enforcement, Coq result, and Java study;
- the project's already-audited primary sources on configuration structures,
  linear/capability resources, anti-rollback, output commit, and supervisory
  control.

Validated local PDFs:

| File | SHA-256 |
|---|---|
| `reference/closest-work/authorization-continuity-fixed-ceiling.pdf` | `6c20cdb3a29f660a9f258ad2bbc6982482eb9953d3b141cfdb505837404b1ba3` |
| `reference/closest-work/lingering-authority-portico.pdf` | `45efdfa3d5a16a712f964ae79dbc46df8ef843904da137ad4baeebf83b125f84` |
| `reference/foundations/secure-the-clones.pdf` | `2bb4d8c5ac85ab034c81e2671448fad63e7686ca2944928e048436f232c8c91a` |

## Verified evidence and decisions

- **Reject Claim 1.** The July 2026 paper explicitly formulates authorization
  continuity, a transition envelope, immutable effect ceiling, attenuation,
  gated ascent, no amplification, and monitor-view closure.
- **Reject Claim 2.** PORTICO already compiles explicit contracts to epoch-bound
  resource/effect capabilities and revokes stale handles. Version hashing is
  engineering, not novelty.
- **Reject Claim 3.** Plan 9 already exposes a per-resource clone vector, while
  *Secure the Clones* verifies a declared maximum-sharing clone policy. A table
  of state actions alone cannot carry a CSF contribution.
- **Retain Claim 4 as acceptance-blocked.** No inspected source jointly
  synthesizes (i) controller coordination required by a future co-durability
  contract, (ii) authority-cell aliasing required by local lineage
  injectivity, and (iii) durable-receipt/lease refinement for a typed dynamic
  Fork/Restore/Merge operation. Static factorization and supremal control are
  classical substrates; the operational composition and compiler theorem must
  carry the contribution.
- **Retain Claim 5 as acceptance-blocked.** The proposed distinction from epoch
  fencing is proof-certified reuse: a lease survives only through a checked
  configuration/lineage/receipt morphism. A necessity theorem and realistic
  nontrivial-reuse cases are still required.

## Refined technical target

Input:

```text
runtime resource manifest
+ typed Fork/Restore/Merge topology contract
+ exact future co-durability family
+ authority lineage and outstanding leases
+ durable effect receipts
```

Output:

```text
greatest pointwise-safe subfamily of fixed candidate semantics
  (under complete observation and controllable pruning)
+ finest exact factorizing partition
+ required authority-cell alias/reissue relation
+ runtime actions (copy/share/split/persist/revalidate/reject)
+ refinement certificate or minimal counterexample
+ Pareto repairs when implementations are incomparable
```

For a finite downward-closed family on its support, the minimal-nonface
hypergraph supplies the static coordination criterion: a partition's join of
block restrictions is exact iff it does not cut a minimal nonface.
This is classical simplicial/relation factorization machinery and will be
credited as such. The agent-specific theorem must place that result inside an
operational transition that also preserves lineage injectivity and durable
commitment monotonicity.

## Remaining uncertainty

- Whether an existing dynamic separation-logic construction already packages
  all three obligations under a resource morphism.
- Whether the finest exact factorizing partition and minimum alias quotient
  interact monotonically enough to admit one canonical compiler result; if not, the tool
  must return a Pareto frontier under an explicit backend language.
- Whether live runtime manifests expose an exact outcome contract; conservative
  over-approximations preserve soundness but lose completeness.
- Whether proof-certified lease reuse occurs often enough in real Claude/Codex
  traces to justify more than a formal expressiveness claim.

## Next action

Mechanize the exact partition criterion and a cut-minimal-nonface
counterexample, then
embed them in one typed clone transition together with the already checked
cell-lineage and durable-receipt semantics. Only after hostile proof review
should the small compiler implement the corresponding witness format.
