# Step 0006 report: formal novelty gate and real-trace schema audit

## Questions and decisions

This step asked four linked questions:

1. whether Boundary II is a genuinely new serialization result or a direct
   instance of established concurrency structure;
2. whether the theorem survives its current assumptions and can be stated over
   the authoritative Lean lifecycle rather than a bespoke abstraction;
3. whether real agent traces expose the state needed to decide safe
   checkpoint/restore; and
4. whether the current RQ2 theorem can pass a real mechanization preflight.

The answers are deliberately asymmetric. The workload and security problem
survive, and no inspected source states the exact authority-specific
final-support certificate. The generic operational content of Boundary II is
not new, however, and the Lean preflight is inconclusive. No paper theorem
claim changes in this step.

## Closest-work and theorem boundary

The primary-source map found that Boundary II's left side is the established
shape of batch-local transition independence:

- Flanagan--Godefroid require preservation of enabledness and commutation;
- Katz--Peled permit independence conditioned on a state predicate;
- van Glabbeek--Plotkin's asynchronous step requires every intermediate
  configuration; and
- Fecher--Majster-Cederbaum model executed events disabling future events and
  deleting them through a remainder operation.

The source-specific identity is still useful. Exact authority repair is
antitone in the promoted owner set, while promoting an owner's own group is
neutral for configurations witnessing that owner's support. Under the frozen
batch and immediate-cleanup assumptions, these facts derive

\[
K_O=\bigwedge_{b\in O}\mathsf{Supp}_b(F_O)
\]

as a complete one-final-policy guard for the full owner-order cube and equality
with an atomic seal. No inspected source gives that formula or refinement, but
the result must be framed as an authority-specific conditional-independence
certificate rather than a new concurrency theory. The complete map is
`formal-closest-map/report.md`.

A separate assumption stress test confirms the intended theorem under source
well-formedness, a fixed batch, nonnegative demand, exact prefix repair, eager
cleanup, and no interleaving. It also supplies countermodels when the hidden
owner-support well-formedness condition, source-fixed ownership, exact repair,
or immediate cleanup is changed. Those assumptions must be explicit in any
future statement. The full matrix is `boundary2-stress/report.md`.

The attribution of *Resource-Tracking Concurrent Games* was corrected to
Aurore Alcolei, Pierre Clairambault, and Olivier Laurent.

## Selected-order correction and prior-art ceiling

The stress analysis initially suggested subset dynamic programming when the
all-orders certificate fails. A second proof/prior-art audit replaces that
claim with a stronger and simpler result. For owner `b`, let `p_b` be its
promoted demand vector and `h_b = G - d - r_b` its vector start deadline. In
the current well-formed, downward-closed, nonnegative model, singleton `{b}` is
the cheapest support witness. Hence

\[
\mathsf{Supp}_b(F_S)
\quad\Longleftrightarrow\quad
\sum_{a\in S\setminus\{b\}}p_a\le h_b.
\]

A backward algorithm repeatedly chooses any owner that remains supported after
all other currently remaining owners. Eligibility only grows as owners are
removed, so no backtracking is needed. Emptying the set returns a safe forward
Prepare order; getting stuck returns a choice-independent authority-dead core
and one overloaded coordinate per owner. The algorithm uses `O(n^2 k)` direct
arithmetic (`O(n^2)` generic support queries), while the scalar case reduces to
ordinary earliest-due-date scheduling. Boundary II is exactly the all-orders
corollary in which every owner is eligible initially.

This is a useful runtime correction but not new abstract scheduling theory.
Möhring, Skutella, and Stork give the same feasibility peeling and generalized-
cycle obstruction for AND/OR precedence constraints. Conflict-free Dual Event
Structure traces give the same reversed AND-of-OR condition, and Ardila--Maneva
pruning/antimatroid theory gives monotone removal and the unique core. The
complete 1,013-line primary-source audit and proofs are in
`killer-hypergraph/report.md`.

The audit also makes the next useful decision precise: serialize the peelable
owners or coordinate a chosen remainder as one final atomic seal. It records an
exact final-seal criterion, a scalar pure-choice weak-NP-completeness reduction,
and a rank-two explicit-killer reduction. Generalized deadlock repair is strong
closest work, so hardness alone is not a paper contribution; those reductions
also remain internal until independently reviewed and mechanized. The plausible
new contribution is a version-bound schedule/core/seal certificate whose
validity is proved across Fork/Restore/Merge/Abort/Revoke and atomically tied to
the pre-dispatch ticket.

## Direct 2026 closest-work correction

Full-text audits of Crab and ACRFence materially narrow the paper's novelty
story:

- Crab already owns the agent--OS semantic gap, full sandbox checkpoint/
  restore, proactive rollback, speculative fork, and RL rollout branching. It
  does not model bounded external authority, co-durable futures, protected
  external effects, promotion, or merge admission.
- ACRFence already owns semantic rollback, Action Replay, Authority
  Resurrection, an irreversible-effect log, and a replay-or-explicit-fork
  mitigation. Its mitigation is not implemented. It separately checks
  consumed credentials, so the fair gap is not arbitrary reuse after fork;
  it is the absence of an authority derivation and aggregate co-durability
  invariant for the new branch.

The broad “agents make rollback unsafe” contribution is therefore preempted.
The surviving center is advance bounded authorization over co-durable futures,
topology-sensitive fork/restore/merge admission, Boundary I's exact
factorization criterion, and the authority-specific part of Boundary II. The
full claim audit is `new-cr-closest-audit/report.md`.

## Real Trace Commons audit

All 30 public Trace Commons rows were inspected read-only at pinned main
revision `112ebd4d03ce852b00e935d523107c3d0c9a65bf` and Viewer parquet revision
`72c58f6a93393d75b1cbff4369430deda2f19c48`. No donated raw trace was copied
into the repository.

| Observable fact | Count |
|---|---:|
| Trace events | 18,012 |
| Tool calls / results | 4,264 / 4,262 |
| Explicit result errors | 269 |
| File-history snapshot events | 953 |
| Snapshot roots / updates | 351 / 601 |

The same sessions include commands aimed at Git remotes, networks, running
processes, package stores, databases, and deployment systems. The two calls
without matching results are uncertain observations, not proof of no effect or
of an unsafe rollback. The trace has ordinary call/message lineage and local
file snapshot metadata but no trusted semantic Fork/Restore cut, grant/claim
lineage, protected-effect phase, durable receipt, or compensation/idempotence
contract.

The trace therefore validates three distinct state planes: reconstructable
workspace state, monotone lifecycle/authority state, and external reality. It
supports workload relevance and an observability-gap result; it cannot supply
ground-truth unsafe-history labels. Full methods and overlapping command-shape
counts are in `trace-commons-audit.md`.

## Experiment-001 integrity chronology

The frozen RQ was:

> RQ2: What changes when a conditional effect becomes durable? Can exact
> promotion remain inside the natural choice/parallel policy language, and
> when does algebraic repair correspond to an executable ordering of effects?

The plan in `experiment-001/plan.md` targeted source-fixed owner groups and the
actual `PrepareOK`/`CoreStep.prepare` transition. Independent plan review in
`experiment-001/plan-review.md` accepted the design but capped the novelty at a
one-final-policy authority certificate plus atomic refinement.

The real Lean preflight stopped after the frozen maximum of three attempts:

1. the default environment had no `lake` on `PATH`;
2. the pinned environment exposed namespace/type shadowing; and
3. the intended module elaborated far enough to expose 15 remaining proof
   obligations, but did not compile and printed declarations containing
   synthetic `sorryAx`.

The third failure is proof engineering, not theorem counterevidence. The
independent result review in `experiment-001/result-review.md` therefore marks
the run **inconclusive**, rejects the draft as proof evidence, prohibits a
fourth attempt, and forbids a paper-claim update.

The exact failed source is preserved outside the Lake source glob as
`experiment-001/preflight/Serialization.failed.lean.txt`, SHA-256
`bb25e8fa5f47576da00511a734c55b2c5db241b1115f4f0ff404f9884b535faa`.
After isolation, the unchanged authoritative library completed a 755-job
regression build. Its log is
`experiment-001/restoration-baseline-build.log`; this is repository hygiene,
not a fourth research preflight or RQ2 evidence.

## Disposition and next gate

No broad trace benchmark and no retry of the same Lean draft are justified.
The selected-order algorithm and its static prior-art boundary are now known.
The next experiment must be materially revised around the agent-specific part:
prove a lifecycle certificate-preservation/invalidation theorem, review and
mechanize the serial-or-final-seal result, and install the versioned decision
atomically with a real pre-dispatch ticket. This preserves the theory-first
direction while making the output directly usable by an industrial runtime.
