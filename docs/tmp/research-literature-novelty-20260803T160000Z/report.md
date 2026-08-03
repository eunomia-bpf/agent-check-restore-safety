# Closest-work and novelty audit: Agent history security state

Date: 2026-08-03

## Claim under audit

The paper's large claim is an end-to-end characterization for history-rewriting
Agents. From an authenticated Fork/Restore/Merge history and irreversible
effects, the theory derives the edit-specific security state, decides whether
an exact prefix-robust realization exists, constructs the greatest realization
or an impossibility certificate, and realizes an admitted edit through a
durable epoch cut.

The audit tests whether recent Agent recovery, transaction, and reversible
execution work already establishes that complete claim. It does not search for
a smaller replacement thesis.

## Primary sources checked

| Work | Status verified on 2026-08-03 | Primary source | Closest overlap |
|---|---|---|---|
| Yu et al., *Shepherd: Enabling Programmable Meta-Agents via Reversible Agentic Execution Traces* | arXiv v3, 24 June 2026; not treated as a peer-reviewed publication | [arXiv abstract](https://arxiv.org/abs/2605.10913), [full HTML](https://arxiv.org/html/2605.10913v3), [artifact](https://github.com/shepherd-agents/shepherd) | Typed task/effect/scope traces; fork, revert, merge, and discard; Lean-mechanized trace algebra |
| Chen et al., *Cordon: Semantic Transactions for Tool-Using LLM Agents* | arXiv v1, 16 June 2026; the manuscript carries a EuroSys 2027 submission header, but no acceptance record was found | [arXiv abstract](https://arxiv.org/abs/2606.17573), [full HTML](https://arxiv.org/html/2606.17573v1) | Task-level semantic transactions, result lineage, staged effects, delegated authority, outbox, recovery log |
| Yang et al., *DART: Semantic Recoverability for Structured Tool Agents* | arXiv v1, 22 May 2026; not treated as a peer-reviewed publication | [arXiv abstract](https://arxiv.org/abs/2605.23311), [full HTML](https://arxiv.org/html/2605.23311v1), [artifact](https://github.com/KeoYang/DART) | Conditions under which a failed task instance can be locally restored despite downstream work |
| Chang and Geng, *SagaLLM: Context Management, Validation, and Transaction Guarantees for Multi-Agent LLM Planning* | PVLDB 18(12):4874--4886, 2025, DOI 10.14778/3750601.3750611 | [PVLDB PDF](https://www.vldb.org/pvldb/vol18/p4874-chang.pdf), [DOI](https://doi.org/10.14778/3750601.3750611) | Saga-style compensation, dependency tracking, persistent context, and validation |
| LangGraph persistence and time travel | Current official product documentation checked 2026-08-03 | [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [Use time travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel), [side-effect contract](https://docs.langchain.com/oss/python/langgraph/functional-api) | Checkpoint replay, fork, and state update in a deployed Agent runtime |

Local primary-source copies (PDF bytes are intentionally git-ignored):

- `docs/reference/closest-work/2026-yu-shepherd.pdf`, SHA-256
  `6f33ed86837aa6df7a753c5917ca00c6ff190105ee66e6116f942250c3a00bd9`;
- `docs/reference/closest-work/2026-chen-cordon.pdf`, SHA-256
  `4abfc0bd9941559b6eb0b15a268c91f67601f72539f85fbc19848b7801f7a713`;
- `docs/reference/closest-work/2026-yang-dart.pdf`, SHA-256
  `8e57b882c47c9456edc88e4c012041d07e171415fb769ffb7e10f546b5a1e572`;
- `docs/reference/closest-work/2025-chang-sagallm.pdf`, SHA-256
  `d7e4f525e2e9c9f847de273edd6bc1e8cbab6e277685dcd673949c0f148d9f97`.

## Claim-oriented comparison

The paper's four factors are semantic distinctions, not a prescribed database
layout:

- **P — promised completions:** which structurally registered outcomes remain
  promised after an edit, including causal order, compatible markings, and
  certified retirement;
- **I — effect identity:** which copied logical occurrences denote the same
  semantic effect cell, together with the authenticated lineage, invocation,
  and gate data that make that incidence trustworthy;
- **E — escaped effects:** which semantic cells already have durable receipts,
  stable result futures, and ordered outbox records, plus the residual policy;
- **C — exact cut:** which history, receipt, logical-resolution, policy/schema,
  and epoch versions may be installed atomically.

| Work | P: promised completions | I: occurrence--cell identity | E: durable escaped effects | C: exact install cut | Missing boundary relative to the paper |
|---|---|---|---|---|---|
| Shepherd | Typed task/trace structure and explicit branch operations provide part of the causal topology | Typed intent/outcome events and a content-addressed commit graph exist, but the checked model does not quotient copied logical occurrences to one semantic effect cell | Reversibility tiers and audit records describe effects; irreversible effects materialize when emitted and can only be recorded for audit | Atomic agent/environment branching and trace checkout provide edit mechanics, not a receipt-and-logical-frontier cut with epoch fencing | Does not characterize safe completion of every promised outcome, derive a greatest monitor, or prove a durable handoff under fresh/alias races; retries, recovery, scheduling, and multi-branch replay are outside its formal envelope |
| Cordon | Scope, intents, result lineage, dependencies, and validation constrain one semantic transaction | Semantic result objects, lineage, and idempotency keys provide partial identity evidence | Effect outbox, recovery log, staged state, acknowledgement, and release status give strong transaction evidence | Transaction status and release form a commit boundary | Takes a task transaction as the unit; it has no Fork/Merge history semantics, outcome-indexed prefix obligations, or copied occurrence--cell aliases, and describes an operational design rather than a formal characterization |
| DART | Producer/consumer relations, reviewed skeleton contracts, and committed-conflict tests express obligations around a failed instance | Concrete task-instance and checkpoint identifiers plus conservative read/write dependencies provide local identity only | `EffectAllowed` and committed-downstream facts account for part of escaped-effect state | `Stable`, checkpoint recency, and `ScopeOK` constrain one local restore boundary | Answers a strict subset: admissible local Restore. It has no Fork/Merge, greatest prefix-robust realization, semantic-cell quotient, successive-edit closure, or receipt-cut race model |
| SagaLLM | Dependency graphs, planning constraints, and validation track workflow obligations | Operation inputs/outputs and transaction/log identities provide partial workflow identity | Saga logs and compensations track executed work | Persistent context, snapshots, and rollback checkpoints provide a workflow recovery boundary | Compensation and validation do not identify when copied occurrences share one irreversible effect or characterize all safe history-edit realizations; formal verification is future work |
| LangGraph | Graph state and next-node metadata expose control state, not promised alternative outcomes | Thread, checkpoint, task, and node identifiers name runtime records | Pending writes are persisted, but the documentation places idempotency on the application and warns that replayed side effects can execute again | Checkpoint IDs support replay, fork, and state update without a security cut over external effects | Supplies the mechanism that needs admission; official documentation does not claim the paper's security characterization |

## Decisive separations

First, consider two individually safe outcomes sharing a prefix. One next step
can retain a safe completion for the chosen outcome while stranding another
outcome that is still structurally promised. None of the five checked works
defines this outcome-indexed shared-prefix obligation for a history edit.

Second, consider two authenticated Agent histories with the same task graph,
checkpoint, transaction status, dependency edges, authority labels, and one
visible receipt. Both restored targets contain logical occurrences \(x\) and
\(y\). In one history, the two occurrences alias the same semantic cell; in
the other, they denote two distinct cells. Under a policy that permits one
authority redemption, the first target resolves as `Fresh(x,d);
Alias(y,d)` and is admissible, whereas the second resolves as
`Fresh(x,d0); Fresh(y,d1)` and is not.

The opposite answer does not follow from ordinary task IDs, causal
dependencies, compensation classes, checkpoint IDs, or a transaction's
released/not-released bit. It requires authenticated occurrence--cell
incidence. A third pair keeps occurrence--cell incidence fixed but changes
which cell the durable receipt names; it requires receipt--cell incidence.

Finally, the same target and ledger can be installable or stale depending on
whether an old protected call linearizes before or after the edit cut. That
decision requires the history/version/epoch relation in C, not merely a
checkpoint or transaction commit bit.

This audit does not claim that the competitors are incapable of being
extended. For example, Cordon's lineage, outbox, and recovery records are a
plausible realization substrate after adding registered history-edit
semantics, outcome promises, semantic-cell aliases, and the exact cut. Such an
augmentation would supply the very security-state information that the
paper's characterization derives and proves observationally necessary.

## Novelty judgment

Same-claim risk is **medium-high**, because the 2026 preprints make reversible
Agent traces, semantic transactions, and restore admissibility a crowded and
fast-moving area. The paper must cite and distinguish all five sources.

The large thesis nevertheless survives:

> Existing systems separately expose reversible traces, semantic
> transactions, admissible local rollback, compensating workflows, or
> checkpoint replay. Agent History Admission asks the end-to-end security
> question they leave open: from an authenticated branching Agent history and
> irreversible receipts, what complete state determines whether a
> Fork/Restore/Merge rewrite has any exact prefix-robust implementation? The
> theory derives that state, constructs its greatest implementation or an
> impossibility certificate, and refines an admitted edit to one durable
> atomic history cut.

The strongest novelty is therefore not the fixed-point iteration by itself,
nor checkpointing, compensation, idempotency, or epoch fencing in isolation.
It is the exact security-state characterization that connects authenticated
history semantics to synthesis, information lower bounds, arbitrary finite
edit sequences, and durable realization.

Unsafe positioning:

- “first reversible Agent runtime”;
- “first semantic transaction for Agents”;
- “first criterion for safe Agent rollback”;
- “first use of compensation/checkpoint replay”;
- “first greatest nonblocking controller.”

Strong, supportable positioning:

- the complete information state for exact Agent history admission;
- an iff characterization covering typed Fork, Restore, and Merge;
- representation-independent opposite-answer lower bounds for promised
  outcomes, occurrence--cell incidence, receipt--cell incidence, and the exact
  cut;
- compilation to the greatest prefix-robust monitor or a finite impossibility
  certificate;
- refinement of an admitted edit to an ideal atomic Agent-history machine.

## Search and verification log

The audit began from four independent CSF reviewer leads and one official
runtime lead. Exact-title searches located arXiv or publisher records. The
full primary texts were downloaded and parsed, and the following terms were
checked in context: fork, revert, restore, merge, irreversible, receipt,
idempotency, lineage, effect outbox, recovery log, committed conflict,
checkpoint, compensation, replay, re-execute, and Lean. Metadata was checked
against the first page and primary landing page. Product behavior was taken
only from official LangGraph documentation.

## Residual uncertainty and update triggers

- Shepherd, Cordon, and DART are recent preprints and may acquire new versions
  before submission. Recheck their primary pages at the final citation gate.
- No official record currently supports describing Cordon as accepted at
  EuroSys 2027. Absence of that record is not evidence of rejection.
- The comparison establishes separation from the checked models and claims;
  it is not a universal non-encodability result for every possible extension.
- If any later version adds authenticated semantic-cell aliases,
  outcome-indexed prefix robustness, or a receipt/logical-frontier install
  cut, rerun the same-claim audit before submission.
