# Open-future agent graphs: novelty and theorem boundary

Date: 2026-08-02

## Verdict

An agent execution graph need not be known extensionally before execution, but
its possible extensions must be constrained intensionally.  Unknown future
node identities, online graph growth, dynamic dependencies, rollback, clone,
and fuse are not new formal phenomena.  The defensible paper question is
narrower: what authority-relevant future contract must an agent runtime expose
when `Fork`, `Restore`, and `Merge` rewrite which durable outcomes may coexist,
while one-shot authority commitments remain outside rollback?

The paper must not claim novelty for dynamic execution graphs or for the mere
existence of distinct control and external-effect histories.

## Prior-art ceiling

- Process calculi and their event-structure semantics already generate
  unbounded processes, fresh names, and topology online.  A representative
  primary source is
  [Crafa--Varacca--Yoshida](https://www.lacl.fr/~dvaracca/papers/eventpi.pdf).
- [Dynamic Causality Event Structures](https://arxiv.org/abs/1801.02857)
  allow occurrences to add or remove causal dependencies during a run.
- [DCR Graphs](https://arxiv.org/abs/1110.4161) dynamically include and
  exclude events for case-management workflows whose operation order is not
  fixed in advance.
- Graph-rewriting concurrency results already cover runtime creation,
  deletion, clone, and composition; examples include
  [DPO rewriting](https://arxiv.org/abs/2105.02309) and
  [SqPO rewriting](https://arxiv.org/abs/2105.02842).
- Reversible event structures already give event semantics to rollback;
  see [Ulidowski--Phillips--Yuen](https://doi.org/10.1007/s00354-018-0040-8).
- Rollback recovery already separates checkpoint state, causal/determinant
  history, and output committed to the external world.  The classic survey
  treats output commit explicitly:
  [Elnozahy et al.](https://www.cs.rice.edu/~dbj/pubs/csur-rollback.pdf).
- VM rollback work already observes that execution becomes a tree and places
  security state in rollback-independent storage:
  [Garfinkel--Rosenblum](https://www.usenix.org/legacy/event/hotos05/prelim_papers/garfinkel/garfinkel_html/index.html).
- Environment contracts and partial-observation control already make
  soundness/completeness relative to assumptions about future behavior; see
  [Interface Automata](https://doi.org/10.1145/503209.503226).

Consequently, the mathematical expression power is available in traditional
models.  A contribution must instead identify and enforce the right agent
runtime interface.

## Three levels of specification

1. A completed run has an extensional realized graph and can be reconstructed
   if the trace is complete.
2. A concrete future graph normally cannot be predicted because LLM choices,
   tool results, users, and external state are nondeterministic.
3. A typed transition system can specify the grammar and contracts of every
   permitted extension without enumerating the graph.

The paper operates at level 3.  Let `p` be the current execution prefix and
`Gamma` its versioned future contract.  `Future_Gamma(p)` is a symbolic family
of redemption-cell configurations that may still become jointly durable.
The runtime does not need future branch IDs.  It needs a conservative account
of authority-relevant co-durability.

The contract contains at least:

1. semantic redemption-cell identity, not only a handle or operation label;
2. the lineage map from cells to source unit authority;
3. the durable spent/Prepare prefix, retained after settlement;
4. the co-redeemable configuration family induced by future operators;
5. typed transformations for Fork, selection, abort, Restore, and Merge;
6. a version/hash and authority for approving topology expansion;
7. stable operation key, effect digest, epoch, commitment, and receipt binding;
8. complete mediation of every protected Dispatch through Prepare.

## Exact future-observation boundary

Take two detached cells with one lineage:

```text
lineage(d0) = lineage(d1) = u.
```

The two worlds have the same current prefix.  Their future contracts differ:

```text
Exclusive = downwardClosure {{d0}, {d1}}
Parallel  = Exclusive union downwardClosure {{d0, d1}}.
```

With one source unit `u`, the exclusive world safely reuses the lineage while
the parallel world admits a capacity-one double redemption.  A checker that
must now materialize independently redeemable authority, observes only the
common prefix, and has neither shared ratification nor delayed delegation must
make the same decision in both worlds.  Acceptance is unsound in `Parallel`;
rejection is incomplete in `Exclusive`.

This is a standard indistinguishability argument specialized to an agent
lifecycle, not a general partial-observation discovery.  Its premises matter:

- a computation-only Fork can always be accepted and authorization delayed;
- aliases behind one durable linearizer do not create independent cells;
- a worst-case-parallel checker is sound but deliberately incomplete;
- the completeness claim is relative to an exact, decidable contract language.

Thus the useful statement is:

> Before issuing independently redeemable branch authority, a sound and
> maximally permissive online runtime needs an exact authority-relevant future
> contract, a shared durable linearizer, or deferred delegation.

## Online preservation rule

For durable prefix `P`, current/proposed state `S`, and contract `Gamma`, the
exact admission condition is

```text
for every C in Future_Gamma(S):
  lineage is injective on P union C, and
  lineage[P union C] is covered by an allowed source configuration.
```

- If `Future_Gamma` overapproximates real futures, the monitor is sound but may
  reject safe executions.
- If it underapproximates real futures, soundness is lost.
- If it is exact and its representation is decidable, structural completeness
  is possible relative to that contract.
- Contract restriction can retain an existing certificate.  Contract
  expansion requires admission before the added future becomes reachable.
- An already delegated detached right that cannot be revoked or fenced makes
  an unsafe expansion reject-only unless fresh source authority is supplied.
- Outstanding authority is bound to the contract hash so that a later Merge
  cannot silently change exclusivity into co-durability.

This converts an unknown complete graph into an inductive operator check.

## Remaining candidate contribution

The candidate contribution is not another event-structure formalism.  It is a
typed refinement interface for agent runtimes:

```text
history/control prefix + future contract
    -> semantic redemption cells
    -> source authority atoms
    -> monotone commitments and external receipts.
```

The theorem package must derive, rather than assume:

1. arbitrary compliant future extensions preserve every additive authority
   policy;
2. topology expansion is checked before reachability and cannot silently
   broaden an outstanding authority contract;
3. spent receipts prevent Restore resurrection across time;
4. failure of the certificate is repaired only by shared linearization,
   durable exclusion/fencing, fresh authority/escrow allocation, deferred
   delegation, or rejection;
5. the concrete Claude/Codex mediation boundary supplies the claimed cell,
   contract, commitment, and receipt observations.

If only the classical configuration morphism or global escrow invariant
survives, this direction is not a sufficient headline contribution.
