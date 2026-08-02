# A theory-guided history-admission compiler

## What to build

The right tool is a small offline compiler and independent verifier, not a new
checkpoint engine.  It sits at the admission boundary of a runtime operation:

```text
typed Fork / Restore / Merge manifest
        + durable receipt frontier
        + authority and future contract
        + cell and controller evidence
                        |
                        v
              untrusted compiler
                        |
        continuation envelope + witnesses
                        |
                        v
              independent verifier
                        |
          structural history-admission seal
```

The runtime may integrate this hook before installing a fork, restore, or merge
edge.  The compiler does not run an LLM, capture a process image, or mediate
tools itself.

## The semantic object

A snapshot is not the security state.  The relevant state has two temporal
halves:

- a fixed, monotone durable prefix `D` of external commitments that restore
  cannot erase; and
- a downward-closed family `F` of future semantic commitment cells that may
  still become durable together.

Each cell has a lineage atom.  A family retains correlation: choice permits
either singleton without permitting their union, while tensor admits compatible
unions.  Thus a history transformation changes authority even when it copies no
new bytes and creates no new bearer capability.

For a generated candidate family `C`, the exact durable-prefix-safe residual is

```text
SafeFuture = {
  X in C |
  X replays no atom in D,
  lineage is injective on X, and
  D union lineage(X) belongs to the authority family
}.
```

The typed operator also generates a required family `R`.  This yields four
semantic outcomes relative to the declared contract:

- `Inherit`: a version-monotone structural refinement transports the old
  envelope;
- `ReadmitOK`: inheritance is unavailable, but the complete candidate is safe;
- `NeedsMechanism`: the complete candidate is unsafe, while `R` fits inside the
  greatest safe residual; or
- `Reject`: a required configuration lies outside the residual.

This is not a heuristic classification.  Coverage and pairwise exclusivity are
the theorem obligations.

## Two independent identities

The critical separation is:

```text
handle occurrence  --q_D-->  semantic redemption cell
gate use           --q_G-->  authoritative controller instance
```

The first quotient answers whether two names redeem the same atomic semantic
commitment.  The second answers whether two executions share the state that
maintains a correlated future contract.  Neither quotient determines the
other.

Consequently, two fork arms may correctly alias one redemption cell yet pass
through cloned controllers.  Atomic redemption prevents duplicate consumption
of that one cell, but cloned gates can still destroy a higher-order correlation
among several cells.  Conversely, multiple controllers are harmless for a full
powerset contract with no correlation to preserve.

## Physical realization

Let `L_g` be a controller's local family and `Gamma` the declared family of
controller sets that may be live together.  Under the independent-product
abstraction, the physically realizable family is

```text
Physical = union over G in Gamma of tensor over g in G of L_g,
```

computed after semantic-cell normalization.  Safety and fidelity are distinct:

```text
Required <= Physical <= Admitted     structural readiness
Physical = Admitted                  exact fidelity
```

A strict middle inclusion is a safe implementation that omits only optional
behavior.  An over-permission witness is classified before it is named.  A
physical cell outside `support(Admitted)` yields `OutsideSupport`, not a fake
minimal nonface.  Within support, a chosen local controller configuration that
is already forbidden yields `LocalOverpermission`.  Only when every local
choice is individually admitted does a forbidden union yield
`CorrelationCut`, with `GateClone` and `GateCut` as same-origin and
distinct-origin subcases.  The certificate restricts the chosen local
configurations to an inclusion-minimal controller cover of the actual minimal
nonface.  `Required - Physical` is a missing behavior error rather than a
security over-permission.

This remains a manifest-relative result.  For an actual runtime family
`Actual`, the deployable refinement obligation is

```text
Required <= Actual <= Physical <= Admitted.
```

The compiler checks the outer model sandwich but cannot establish the two
relations involving `Actual`; complete mediation, runtime soundness against
the declared product, and required-behavior coverage remain external adapter
obligations.

The connected components of the minimal-nonface hypergraph give the finest
functional controller partition that preserves every correlation.  A runtime
can use these components as a coordination-placement plan.  The more general
access-relation theorem, where one cell is reachable through several gates, is
the next mechanization target.

## What the compiler synthesizes

The compiler produces useful artifacts rather than a Boolean answer:

1. normalized semantic cells and explicit alias evidence;
2. typed candidate, required, and greatest safe families;
3. a structural parent map when inheritance succeeds;
4. lease-binding transport decisions, explicitly scoped below full lease
   validity;
5. the physical controller family and refinement grade;
6. minimal prefix, lineage, forbidden-union, gate-cut, or gate-clone witnesses;
7. finest mandatory coordination components; and
8. a versioned result digest that an independent implementation reconstructs.

The verifier's seal is deliberately not an effect-authorization credential.
It records structural eligibility while leaving manifest authenticity, ledger
completeness, controller freshness, complete mediation, lease validity, and
atomic redemption as explicit runtime obligations.

## Why agents expose the problem

The theory is general to any history-transforming executor, but agents make its
premises common:

- after restore, a model re-synthesizes semantically related calls with new
  textual handles and idempotency keys;
- tool effects escape the rollback domain into payments, tickets, messages,
  credentials, human decisions, and remote services;
- test-time search, subagents, retries, and RL rollouts dynamically introduce
  choice and parallelism rather than following one predeclared workflow;
- merge combines artifacts and authority provenance from histories that may
  never have been jointly live; and
- the neural planner is neither the authority issuer nor a trusted source of
  lineage and exclusivity evidence.

The same admission problem can apply to speculative workflow engines, saga
orchestrators, deployment planners, notebook branches, and search/RL runtimes.
The paper should therefore say “history-transforming computation,” with agents
as the motivating workload and integration target.

## Closest-work boundary

No individual mathematical ingredient should be claimed as new.

- Distributed snapshots and rollback recovery capture consistent past state
  and address output commit; they do not derive the correlated future that
  remains authorized after a lifecycle rewrite.
- Transactions and sagas provide atomicity or compensation for prescribed
  workflows; they do not decide whether independently valid fork arms are
  jointly authorized.
- Idempotency and exactly-once mechanisms deduplicate one logical operation;
  they do not prevent two distinct, individually fresh operations from forming
  a forbidden union.
- Capability and linear-authority systems constrain possession, delegation, or
  use; “fork must not copy a linear token” is therefore not a novelty claim.
  The new issue is the independent distortion of redemption-cell and
  enforcement-gate identity.
- Event/configuration structures already represent causal and conflicting
  configurations, including higher-order conflict.  They are a semantic
  foundation, not a contribution to rename.
- Security automata and supervisory control already compute maximally allowed
  behavior under established assumptions.
- Proof-carrying code and authorization already separate an untrusted producer
  from a small checker.

The defensible combined claim is narrower and stronger:

> Given a fixed durable receipt prefix, a correlated future contract, and a
> typed history transformation, history admission simultaneously normalizes
> semantic cells, transports operator-specific futures, checks independent gate
> realizability, computes the greatest safe continuation, and emits independently
> checkable positive or minimal negative evidence.

The work must explicitly distinguish ACRFence-style semantic replay protection,
agent sandbox checkpoint systems, formal agent policy/reference monitors,
contract-to-capability compilers, event structures, invariant confluence, and
supervisory control.  The novelty is the lifecycle decision problem and the
cell/gate separation, not any one reused algorithm.

## Theory and evaluation plan

The high-value theorem sequence is:

1. typed family generation and required-subset validity for all six operators;
2. durable-prefix safe residual is downward closed and greatest;
3. structural refinement implies full readmission and composes over a graph;
4. `Required <= Physical <= SafeFuture` is necessary and sufficient for
   structural deployment readiness under the manifest abstraction;
5. any physical over-permission contains a minimal nonface product witness;
6. the functional controller partition theorem is a special case of the
   controller-access cover theorem; and
7. minimal nonfaces synthesize a finest coordination placement or a pruning
   obligation.

Experiments are supporting evidence, not the paper's center:

- mechanize the unbounded theorems and kernel-check them;
- exhaustively cross-check small finite families and independent verifier
  parity;
- translate real Claude/Codex/private paper-development traces into manifests
  and measure which identity, prefix, and controller evidence is observable;
- replay compact Fork/Restore/Merge litmus cases against adapters; and
- report analysis time and certificate size only as feasibility metrics.

Prompt success rates cannot validate the theorem.  Trace data validates the
workload assumptions and adapter boundary; the formal model validates the
admission result.
