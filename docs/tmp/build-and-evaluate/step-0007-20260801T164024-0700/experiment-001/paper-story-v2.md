# Paper story v2: branching histories, linear authority

## One-sentence claim

Agent runtimes may freely copy and transform execution history, but they must
not thereby copy the right to perform a protected effect.  A safe runtime
therefore keeps a non-rollbackable promotion plan with two independent
conservation laws: quantitative resource accounting and a discrete linear
token for each future protected operation.

## Opening failure

An agent has a checked plan containing one zero-resource protected action.  It
forks a history into two descendants.  A vector-only transfer checker accepts
two zero-demand descendants because `0 + 0 <= 0`.  Each descendant can later
be prepared into a distinct durable tool ticket.  Capacity is conserved, but
authority is duplicated.  This is the minimal counterexample that separates
resource conservation from linear operation identity.

This failure is agent-relevant because a fork copies the representation of a
past plan into several model contexts.  Seeing the same plan or token name in
two histories is harmless; accepting two current controller witnesses for it
is not.  The trusted controller, rather than the copied transcript, decides
which occurrence is live.

## Three state planes

1. **Reconstructable state**: files, database snapshots, model context, staged
   payloads, and process memory.  Checkpoint/restore can copy or replace it.
2. **Controller authority state**: branch epochs, plan version, slot/root
   lineage, remaining claims, token origins and dispositions, and durable
   operation tickets.  It is monotone or CAS-protected and is not restored
   merely because a workspace is restored.
3. **External reality**: remote writes, messages, disclosures, payments, and
   uncertain attempts.  It is reconciled through stable operation identity and
   receipts; it is neither a file snapshot nor generally rollbackable.

The paper does not propose “roll back everything.”  Replacing restore, live
restore, fork, and merge intentionally preserve different continuations, and
external reality may be irreversible.  The design instead transports or
consumes authority according to the semantic history operation.

## The mechanism

### Quantitative promotion plan

The controller stores an ordered plan over slots, owner groups, grants, and
claim roots.  For each slot/grant it stores initial promise `P`, residual work
`R`, already promoted load `E`, and explicit withdrawal `W`, with exact
accounting `R + E + W = P` (and a durable baseline/capacity guard).  Fork,
Restore, Merge, Restriction, and Revoke compute the target plan from the source
state and the actual lineage map `rho`; callers cannot assert a target plan or
target validity.

### Discrete origin-token ledger

Each future protected operation receives an immutable initial token at trusted
plan construction.  A token has exactly one of three computed dispositions:

- `remaining`: exactly one current plan claim witnesses it;
- `prepared`: no current claim remains and exactly one durable ticket/receipt
  binding witnesses it; or
- `withdrawn`: neither kind of witness remains.

The current and binding fibers have cardinality at most one and are mutually
exclusive.  Demand may be zero.  A claim is normalized to at most one future
protected operation; a compound or intentionally parallel action must be
expanded into several claims/tokens before plan execution.  Tokens are
controller identities, not bearer secrets or OS capabilities.

### Prepare as the linearization boundary

`Prepare` runs in one durable transaction.  It checks a plan-version CAS,
computes the earliest remaining slot/owner group, validates the assignment,
promotes claims, consumes their current token witnesses, mints stable operation
tickets, recomputes `R/E/W` and token dispositions, and advances the plan
version.  A crash exposes either the old head or the complete new head.

After Prepare, Dispatch and Retry consult only the durable ticket.  They do not
re-read a copied plan, grant epoch, branch, or workspace checkpoint.  Revoke
blocks new Prepare but cannot erase an already prepared operation.  Exactly
once in external reality remains a sink/idempotency/reconciliation obligation,
not a consequence of the logical token theorem.

## Checked history operations

- **Checkpoint** copies reconstructable state and stutters controller
  authority.
- **Choice/parallel Fork** and **replacing/live Restore** use their canonical
  lineage maps.  Quantitative demand may split conservatively, but one token
  can have at most one current descendant.
- **Merge** is accepted only when the computed target preserves slot/root and
  token invariants.  A cross-slot or mixed-root merge can be authority-unsafe
  even if every touched object appears locally unchanged.
- **Restriction/Revoke** compute withdrawal from actual target absence; the
  caller cannot refund or withdraw a supplied set.
- **Prepare** moves a token from current to durable binding.
- **Dispatch/Retry/Crash/Settle** preserve the stable binding while changing
  only effect phase or receipt state.

The checked grammar is a conservative sublanguage of the existing lifecycle
semantics.  The projection is one-way: the mechanization does not claim that
every raw runtime transition was mediated.

## Threat and trust boundary

The model treats model-generated state, copied transcripts, tool arguments,
and restored workspaces as untrusted.  They may be stale, duplicated, or
adversarially chosen.  One durable reference monitor is trusted to mint plan-
epoch tokens, compute lifecycle transports, serialize authority mutations, and
mediate every protected dispatch.  Its transactional store is inside the
trusted computing base; an attacker who can rewrite that store or its anchor
can forge logical authority.  Tokens are logical identities, not cryptographic
bearer capabilities.

The runtime adapter must truthfully classify a history transformation and
supply its actual claim-lineage map.  The theorem cannot recover semantic
lineage from a filesystem diff or natural-language transcript.  Likewise, the
policy must correctly decide which tool calls are protected and how much
resource they demand.  The model proves preservation conditional on these
inputs and complete mediation; it does not prove classifier correctness.

Concurrency is reduced to serialized controller transactions whose offered
plan version must match the durable version.  The proof therefore establishes
sequential checked-history safety, while the implementation separately tests
one concrete SQLite serialization boundary.  A ticket gives stable logical
identity across ambiguous attempts, but physical exactly-once behavior still
requires an idempotent or queryable external sink.

Tokens are fixed only within one installed plan epoch.  A dynamically proposed
tool call first enters through trusted plan installation, which assigns a
fresh token before the plan can be forked or prepared; installing or extending
plans is not modeled as an ordinary copyable history step.  This keeps the
conservation theorem precise while leaving freshness generation and policy
approval as controller obligations.

## Main formal claims

1. **Checker soundness.**  A successful finite token check implies coverage,
   current/binding fiber linearity, mutual exclusion, and exact computed
   disposition.
2. **Per-token trichotomy.**  Every initially minted token is exactly
   remaining, prepared, or withdrawn, with fiber cardinalities `1/0`, `0/1`,
   or `0/0` respectively.
3. **Checked-step preservation.**  Every admitted operation in the token-aware
   grammar preserves lifecycle/plan safety and token linearity.
4. **Arbitrary-history preservation.**  Reflexive-transitive checked histories
   preserve the combined invariant, project to actual lifecycle traces, keep
   the initial token set fixed, and monotonically advance the plan version.
5. **Zero-demand separation.**  The old quantitative checker accepts a
   one-token/two-zero-demand-child Fork; the token checker rejects it and the
   unchecked target fiber has cardinality two.
6. **Observation lower bound.**  Workspace-equivalent states can require
   opposite Restore/Prepare decisions when their controller token/effect state
   differs; no workspace-only guard is both sound and complete.  Global
   versions are sound but over-invalidate disjoint changes, while per-object
   caches miss semantic topology dependencies.

The current mechanization enforces mutating steps by scanning a deterministic
computed target.  It is an executable reference-monitor theorem, not yet a
source-only derivation for every token atom.  Sequential version equality is
not a proof of concurrent linearizability or storage power-loss atomicity.

## Evidence layers

### Lean is the security evidence

Lean defines the finite lifecycle, rich plan, computed transports, token
ledger, checked grammar, zero-demand counterexample, and arbitrary-trace
preservation.  Kernel replay and axiom/static audits delimit the theorem.

### Runtime pilot is the implementation evidence

A separate SQLite pilot places lifecycle, plan, token ledger, event chain, and
tickets in one hashed state.  `BEGIN IMMEDIATE` implements the Prepare/CAS
boundary; an independent replay checker recomputes invariants.  Controlled
tests cover stale copies, target injection, disjoint changes, same/cross-root
Merge, two Prepare rounds, Revoke, restriction, crash/retry/settle, and the
zero-demand token Fork.  Existing Codex App Server tests are compatibility
regression evidence, not proof that Codex natively emits the new metadata.

### The paper's own formation trace is workload evidence

The paper is also a retrospective longitudinal case study: its real Codex task
formed a recursive delegation lineage with full-history and no-history forks,
compaction, abort/recovery, tool calls, and repeated workspace mutation.  Raw
private traces never enter the artifact.  A redacted extractor uses pinned
runtime source contracts to separate inherited representation from child-local
events, emits only allowlisted aggregates, and derives synthetic regression
fixtures from observed schemas.

The case supports three narrow claims:

1. a real long-running agent workload had a branching history topology;
2. copied child logs required provenance-aware normalization; and
3. ordinary telemetry exposed history/controller/workspace shapes but no typed
   plan version, token disposition, Prepare ticket, or external receipt usable
   by the proposed admission check.

It does not estimate prevalence, label any observed history unsafe, validate
the safety algorithm, or treat copied log rows as duplicated effects.  A public
TraceLab audit supplies broader ordinary-tool/schema evidence; synthetic
fixtures test the parser; the formal model and fault-injection pilot carry the
security claims.  Claude contributes lifecycle metadata only because its raw
action traces are not recoverable.

The unit of analysis is the one selected longitudinal lineage, not each child
as an independent task.  The case study asks three deliberately narrow
questions:

1. What branching, inherited-history, compaction, recovery, and workspace-
   mutation shapes occur while this paper is produced?
2. Which of the three state planes are represented by the recorded schema, and
   does it contain typed observations usable by the formal admission check?
3. How much does a provenance-naive event view differ from a source-pinned,
   child-local view, and which observed schema shapes should become synthetic
   runtime regression tests?

The analysis fixes a retrospective cutoff and lineage-selection rule, pins the
runtime versions and their fork-history source contract, rejects unsupported or
ambiguous formats, validates a single-parent acyclic lineage, and emits only
allowlisted aggregates.  The anonymous artifact can reproduce the extractor
on synthetic fixtures and the public corpus, but cannot independently
reproduce private counts.  Accordingly, topology and field-presence results
are descriptive properties of one author-operated lineage rather than a
population estimate or an efficacy evaluation.

The data statement should say that the case was generated by an author-
operated research task, no users were recruited or experimentally manipulated,
and the operator authorized analysis of their local traces.  Raw records may
contain prompts, private workspace material, commands, and incidental third-
party text, so access remains limited to the authors and no raw row, stable ID,
path, command, payload, or result is released.  The distributable artifact
contains only the fail-closed extractor, adversarial synthetic fixtures,
allowlisted aggregates, and public-corpus code.  The paper must not claim IRB
approval or exemption unless the authors actually obtain that determination.

## Paper architecture

1. Introduction: zero-demand duplication and copyable history versus linear
   authority.
2. Real workload and three state planes: private case plus public breadth,
   with privacy/ethics limits.
3. Model: lifecycle, plan roots/slots, quantitative rows, origin tokens, effect
   tickets.
4. Algorithm: computed transport and atomic Prepare/Dispatch split.
5. Theorems and counterexamples: preservation, trichotomy, lower bound, and
   precise nonclaims.
6. Mechanization and pilot: proof audit, adversarial fixtures, independent
   replay, and small baseline comparison.
7. Related work and limitations.

The former residual-contract rectangularity and promotion-order boundaries can
remain as supporting quantitative results or move to an appendix.  They should
not compete with token linearity and atomic promotion for the first-page
headline.

## Proposed title and memorable rule

**Branching Histories, Linear Authority: Safe Promotion Plans for Forkable
Agents**

> History may be copied; authority occurrences may not.  Consume authority at
> Prepare, then execute only from the durable ticket.

## Candidate abstract (evidence placeholders intentionally omitted)

Agent runtimes increasingly fork, restore, and merge execution histories while
tools change state outside any restorable snapshot.  A copied history can also
copy the representation of an unexecuted plan.  Quantitative budgets alone do
not prevent the two copies from authorizing distinct zero-cost operations.
We introduce a promotion-plan semantics that separates reconstructable state,
durable controller authority, and external reality.  Every planned protected
operation has an immutable origin token.  Checked history transformations may
transport or withdraw its current witness but cannot duplicate it; an atomic
Prepare step consumes that witness and creates one durable operation ticket,
after which dispatch and retry depend only on the ticket.  We prove checker
soundness, exact remaining/prepared/withdrawn token trichotomy, and invariant
preservation across a checked grammar of Fork, Restore, Merge, Restriction,
Revoke, Prepare, and ticket lifecycle steps.  A zero-demand counterexample
shows why resource accounting is insufficient, while a paired-state lower
bound shows why workspace-only guards cannot recover the necessary decision.
The results are mechanized in Lean.  A fault-injected SQLite reference monitor
tests the atomic boundary, and a retrospective case study of the agent lineage
that produced this paper characterizes the workload and telemetry gap without
using private traces as correctness evidence.
