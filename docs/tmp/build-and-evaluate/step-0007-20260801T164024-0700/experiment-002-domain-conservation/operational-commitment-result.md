# Operational commitment core result

Date: 2026-08-02

## Verdict

**PASS as the operational Prepare/receipt core after revision.  It is not yet
the typed Fork/Restore/Merge theorem.**

The first version kernel-checked, but an independent hostile review returned
`REVISE`.  It found that the implementation-locality wording was stronger than
the model, external phases were unconstrained, Retry could guess a receipt,
and the label-erased RTC could not relate fresh events to receipt growth.  It
also emphasized that the capacity theorem followed directly from the source
`Safe` invariant and that topology-changing operators were absent.

The revised module repairs those interface issues without enlarging its claim.

## Operational state and boundary

`AuthorityContinuity/RedemptionCommitment.lean` distinguishes:

- immutable issued unit authority atoms;
- semantic cells and their current epochs;
- held rights and explicit cell/epoch-local spent bits;
- stable operation keys and effect digests;
- globally namespaced receipt IDs;
- an append-only immutable receipt ledger; and
- a separate prepared/settled external phase.

The receipt namespace can be implemented by a collision-free cell prefix plus
a cell-local sequence number.  Its freshness prevents two analytic receipt
records from overwriting one another; it does not coordinate two cells' spent
state.  The ledger is an aggregate semantic history and need not be a shared
redemption cell.

`Safe` is stated independently of the transition relation.  It requires
issued ownership, open/unspent held rights, one holder per atom, no atom both
held and committed, at most one receipt per atom, receipt-to-local-spent
consistency, stable idempotency indexing, and ledger/phase domain agreement.
No `Step` constructor accepts target `Safe` or target phase well-formedness.

## Closed operations

The closed core contains:

- Fresh Prepare: validate the selected cell/epoch, consume its held atom, set
  its local spent bit, bind `(cell, epoch, atom, operation, digest)` to a fresh
  receipt, index the stable operation key, and enter `prepared` atomically;
- Replay and Retry: resolve `(cell, operation, digest)` through the stable key
  and existing immutable binding, returning the same receipt without state
  growth;
- Crash: an atomic durable-controller stutter; and
- Settle: advance only the external phase from `prepared` to `settled`.

Crash inside a partially durable physical write, dispatch without a durable
commitment, and sink exactly-once are outside this LTS.

## Proven results

The module proves:

1. Fresh and Settle preserve the independently stated `Safe` and `PhaseWF`
   invariants; Replay, Retry, and Crash are safe stutters.
2. Every closed single step and reflexive-transitive execution preserves
   safety, immutable issuance, append-only receipt bindings, phase-domain
   well-formedness, and phase monotonicity.
3. A retained finite labeled trace has exact receipt growth:

   ```text
   committed(final) = committed(initial) + freshCount(events).
   ```

4. From `Safe`, durable commitment cardinality is at most issued atom
   cardinality.  This is a correct pigeonhole corollary of the source
   uniqueness invariant, not the paper's novelty result.
5. Replay and Retry cannot rebind a stable operation to a different effect
   digest.

## Strict fixtures and their scope

- One capacity-one cell blocks a second fresh commitment.
- Three actual Retry transitions form a labeled trace with zero fresh growth
  and one receipt.
- An explicitly unsafe aggregate that copies one atom into two private cells
  can produce two distinct receipts for the same operation and digest.
- A hand-constructed rollback-local Restore retains the first global receipt,
  reintroduces its snapshot right at another cell, and then creates a second
  receipt.

The last two are operational witnesses, not a general impossibility theorem.
The unsafe clone/Restore states are deliberately outside the safe closed
relation.  The next theorem must show when typed Fork/Restore/Merge can or
cannot construct such a target from a safe source.

## Review repair

The accepted revision:

- replaces a global scan for prior atom use with explicit local spent state;
- states global receipt-name freshness separately and explains its locality;
- adds ledger/phase well-formedness and prepared-to-settled monotonicity;
- binds Retry to cell, operation, digest, and receipt through the durable
  idempotency index;
- retains event labels and proves exact fresh-event accounting; and
- narrows Crash and clone/Restore claims explicitly.

An independent read-only follow-up classified the revised module `PASS` for
this scoped role.

## Validation

The revised module passes standalone elaboration without linter warnings,
the module and integrated library builds, the frozen axiom audit, a fresh
kernel replay of the module, and a fresh kernel replay of the integrated
`AuthorityContinuity.Main` root.  The integrated replay completed with exit
status zero and no diagnostic output.

Current hashes:

```text
1c5b438d05502d074d284720a10c348205b5c50e38491b5f7f1d08b3c9ce2c73  RedemptionCommitment.lean
364e029d20d840865028b7847a7e89b6b36db6e434a585387e3d5d00a573a123  results/axioms.log
364e029d20d840865028b7847a7e89b6b36db6e434a585387e3d5d00a573a123  results/topology-axioms.log
```

The printed dependencies are limited to `propext`, `Quot.sound`, and, for
finite-cardinality/executable fixtures, `Classical.choice`.  No project axiom,
proof placeholder, or `sorryAx` is present.

## Remaining decisive work

The module does not derive `Safe` from a lifecycle topology.  It does not yet
construct the future configuration family independently of authority, bind
outstanding leases to a contract version, prove safe contract expansion, or
cover typed shared/detached Fork, replacing/live Restore, or view/consolidating
Merge.  Those obligations remain the paper-level contribution under test.
