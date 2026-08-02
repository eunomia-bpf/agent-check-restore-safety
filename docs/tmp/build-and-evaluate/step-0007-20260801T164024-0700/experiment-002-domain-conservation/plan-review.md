# Independent plan review

Date: 2026-08-02
Verdict: **REVISE (blocking)**

The review was read-only and independent of the implementation.  It examined
the RQ, hypothesis, theorem boundary, runtime matrix, and completion criteria
in `plan.md`.

## Blocking issue

The proposed global potential

```text
spent + sum of every allocated domain right <= capacity
```

is exact only for the detached profile in which every domain can advance in
isolation and solo executions product-compose.  It is the established escrow /
bounded-counter invariant.  It is not the complete authority-continuity
condition for an agent lifecycle.

A trusted exclusive choice may conditionally expose the same unit in two
alternative rows while atomically selecting/fencing one alternative before
Prepare.  Global summation rejects that safe state.  The complete invariant
must instead range over trusted co-redeemability configurations and quotient
history handles by the semantic cells through which they linearize:

```text
for every grant g and future configuration F,
  charged(g) + sum rights(g,d)
                 for d in image(resolve, handles(F))
  <= capacity(g).
```

Durable commitments occur in every row.  Distinct cells that can each Prepare
under network isolation must occur together in some row; a UI label saying
"choice" is insufficient.  Prepare may consume a right and simultaneously
filter/fence incompatible residual futures.  Scalar conservation remains a
corollary when the configuration family contains the all-domains row.

## Identity and transition corrections

The model must distinguish:

1. a history occurrence;
2. an RPC attempt;
3. a stable operation key used for retry; and
4. a fresh authority commitment/receipt emitted by one cell linearization.

The safety count is over fresh authority commitments, including prepared,
inflight, uncertain, failed, and settled phases.  A ticket is a returned view
of the same commitment and is not counted a second time.  A sink receipt is a
separate external fact.  Same operation key in two cloned cells must yield two
authority receipts even if the final sink deduplicates the external effect.

Fresh Prepare must atomically debit a cell right and create one immutable
commitment bound to `(cell, grant, operation key, effect digest, weight)`.
Prepare replay with the same cell/key/digest returns the existing commitment;
same key with a different digest is rejected.  No core refund is inferred from
failure or cancellation.

Typed operator corrections:

- shared Fork copies handles, not cell state;
- detached Fork debits residual authority before children become independently
  runnable, partitions it, and fences the transferred source epoch;
- replacing Restore closes the old branch epoch durably and resolves the
  restored history against current external cell state;
- live Restore either retains aliases of one cell or performs an explicit
  split;
- view-only Merge only quotients aliases and need not fence;
- consolidating Merge blocks new source Prepare, preserves every commitment
  and uncertain ticket, and performs debit-before-credit residual transfer;
- Retry reuses the same operation key, digest, and commitment;
- epoch validation and quota debit must share the cell linearization point.

## Formal and empirical blockers

- `AdmissibleExtension.singlePerCell` is a useful deployment/refinement
  assumption but cannot be the main operational proof.  The decisive Lean
  result needs balance/commit state and typed transitions from which safety is
  derived.
- `tickets <= capacity` misses settled history.  Use the durable commitment
  ledger, weighted when authority units are not normalized to one.
- A shared-alias preflight must separate four cases: same cell/different fresh
  keys; same cell/same key; cloned cells/different keys; cloned cells/same key.
- The existing Codex callback establishes one effect-boundary seam, not native
  product-wide Fork/Restore/Merge refinement.  Product lifecycle coverage must
  either be instrumented or explicitly excluded.
- A crash after debit but before returning a ticket may lose availability but
  is not a safety failure.  The unsafe cuts are dispatch without a durable
  commitment and external send before that commitment.

## Pass conditions for revision 2

1. Make the configuration-indexed semantic-cell quotient the headline
   invariant.
2. Label scalar conservation as the detached independent-domain corollary.
3. Prove operational balance/commit preservation without taking target safety
   or per-cell uniqueness as a constructor premise.
4. Retain strict witnesses for aliases, cloned state, restoring after use,
   partial-use Merge, same-key retry, and digest conflict.
5. Scope real Codex evidence to the mediated callback seam unless actual
   lifecycle hooks are covered.
6. Keep external exactly-once conditional on a sink protocol and out of the
   authority theorem.

With those changes the experiment is executable and may support a CSF-level
operator-refinement contribution.  Without them it would repackage classical
escrow and conflict with the project's own conditional-authority model.

## Revision-2 follow-up

Verdict: **PASS**.

The follow-up reviewer confirmed that revision 2 makes the
configuration-indexed quotient the headline, treats scalar conservation and
local injectivity as established machinery/corollaries, separates all four
event identities, forbids circular proof premises, and scopes the Codex result
to one mediation seam.

The proof must retain three explicit guardrails:

1. the source configuration family is finite and downward closed;
2. target weights are inherited from unit-normalized source authority atoms
   (a graded split requires a separate quantitative morphism); and
3. the trusted configuration family is complete for actual Prepare
   co-redeemability, including isolated executions that product-compose.

The minimum pre-paper theorem package is: the cell-quotient iff and its two
constructive counterexamples; operational balance-to-commitment conservation;
typed operator and finite-trace refinement; clone/restore necessity and strict
witnesses; and durable-commitment-before-mediated-Dispatch.  External physical
exactly-once remains conditional on the sink protocol.
