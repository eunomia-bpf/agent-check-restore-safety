# Redemption-cell semantic matrix

## Status and evidence role

This is a dependency-level executable semantic oracle for the corrected claim
that handles may be copied while independently redeemable state must not be
amplified.  Its exact scope is the **all-domains-independent/escrow profile**:
rights are scalar, and every safely detached cell can redeem its partition
independently.  It is not the complete conditional-authority model and does not
encode mutually exclusive choice branches, lifecycle-derived co-redeemability
frontiers, or dependencies among domains.

It is not a real-runtime experiment, performance result, or proof.  It does
not replace the existing SQLite/Codex adapter evidence.  The existing
`PlanPilotController` has durable tickets and atomic Prepare, but it has no
first-class handle-to-linearization-cell relation or safe detached
Fork/Restore/Merge operators.  Extending that controller would have mixed this
new model into the frozen adapter, so the oracle is isolated in new files.

## Model boundary

- A `Handle(alias_id, cell_id, epoch)` is freely copyable.
- A cell is the durable atomic redemption/linearization object.  Only
  `cell_id` establishes this identity.  Equal logical labels and equal integer
  epochs do not make two cells the same object, and the implementation never
  uses a logical label to resolve a Prepare.
- A grant is minted as named right tokens.  Prepare atomically moves one token
  from a cell's unspent escrow to a durable, effect-digest-bound ticket.
- Detached fork fences the source and partitions, rather than copies, the
  remaining right tokens.
- Replacing restore rotates the durable cell epoch and does not reconstruct
  consumed rights or receipts from checkpoint values.
- Merge fences each input, carries immutable receipt references, and moves only
  the union of disjoint unspent right tokens.
- `prepare_linearizations` counts durable controller Prepare successes.
  `external_sink_effects` counts later dispatches.  The two are deliberately
  separate.
- `unsafe_clone_private_cell` is a negative-control constructor, not a safe
  lifecycle operation.  It duplicates local right tokens into an independent
  cell so that two locally correct Prepare operations expose the amplification
  witness.

The conservation oracle independently derives violations from token locations
and the immutable Prepare log: duplicate unspent ownership, simultaneous
unspent-and-redeemed state, duplicate redemption, missing rights, or unknown
rights.  Safe lifecycle operations require this independently computed report
before and after their transition.  Local Prepare intentionally remains
cell-local so the unsafe-clone negative control can demonstrate two accepts
instead of rejecting the already-bad global state by definition.

## Executed scenarios

| Scenario | Final controller Prepare linearizations | External sink effects | Result |
|---|---:|---:|---|
| Two concurrent aliases of one capacity-1 cell | 1 | 1 after dispatching the winner (0 before dispatch) | one atomic winner; conserved |
| Two private cloned cells, same capacity-1 logical label and copied right | 2 | 0 | amplification witness; duplicate redemption detected |
| Fenced detached fork with 1+2 escrow partition | 3 | 0 | stale source rejected; all three distinct rights used once |
| Restore after one settled effect under capacity 2 | 2 | 1 | old epoch rejected; prior receipt remains visible |
| Merge two capacity-2 partitions after one settled effect each | 4 | 2 | two receipts retained; exactly two unspent rights transferred and later consumed |
| Crash immediately before Prepare commit | 0 | 0 | right present, ticket absent |
| Crash immediately after Prepare commit | 1 | 0 | right absent, ticket present |
| Stable effect/digest Prepare replay | 1 | 0 | replay accepted without a second linearization; digest rebinding rejected |

The crash-cut rows establish an old-or-new invariant of the oracle's **abstract
durable controller state**: no observed post-crash state contains both the same
unspent right and a ticket for it.  They do not establish physical media
durability, and they make no remote exactly-once claim because no sink dispatch
occurs in either row.

## Reproduction and exact results

Targeted command:

```bash
python -m unittest -v adapter.test_redemption_semantics
```

Latest targeted result: **7 tests passed**, `Ran 7 tests in 0.003s`, `OK`.

Full adapter regression command:

```bash
python -W always::ResourceWarning -m unittest discover -v adapter
```

Latest full verification: **59 tests passed**, `Ran 59 tests in 13.063s`,
`OK`.  This includes
the existing real Codex App Server preflight and all prior controller, replay,
worker-crash, oracle, and artifact checks; the seven new tests are the only
increase over the earlier 52-test suite.

## Files

- `adapter/redemption_semantics.py`: isolated executable model and conservation
  oracle.
- `adapter/test_redemption_semantics.py`: seven semantic scenarios, including
  the six required cases and the stable-effect replay control.
- this report: scope, interpretation, commands, and exact observed results.

## Limitations

The oracle is in-memory and uses a Python lock as its atomic cell.  It does not
establish storage durability, distributed consensus, cross-service fencing,
product-wide complete mediation, or exactly-once external effects.  Its scalar
token equation is not a substitute for the general conditional/co-redeemability
theory.  Its value is to make one important profile and its separating
counterexample executable, and to prevent a paper model from conflating handle
aliases, logical labels, physical/private controller copies, controller
Prepare successes, and sink outcomes.  The production-facing contract would
require the same cell identity and epoch to resolve to a shared linearizable
service, or an explicitly conserved escrow/fencing protocol for creating
independent cells.
