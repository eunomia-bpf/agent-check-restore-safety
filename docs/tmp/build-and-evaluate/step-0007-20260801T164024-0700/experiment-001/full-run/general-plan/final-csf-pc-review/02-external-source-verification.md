# Closest-work and claim verification

## Material collision: copyable evidence plus atomic redemption

Bowers et al., *Consumable Credentials in Linear-Logic-Based Access-Control
Systems* (NDSS 2007), is more than a generic linear-logic precedent. Its
ratification stage occurs after proof construction, globally enforces a bound
on uses, atomically records all uses or none, and binds ratification to the
credential, proof, goal, and nonce so copied proof/ratification material cannot
be productively reused. The paper accurately cites these facts, but does not
answer the decisive alternative they create: why may branches not keep
copyable aliases and race at a single atomic ratifier?

Primary source:
<https://www.ndss-symposium.org/wp-content/uploads/2017/09/Consumable-Credentials-in-Linear-Logic-Based-Access-Control-Systems.pdf>

No searched source stated the submission's exact Fork/Restore/two-Merge
`currentFiber` equality. That preserves a narrow syntactic novelty claim, but
does not establish significance or necessity. The missing comparison is a
formal separation against redemption-only enforcement, not another table row.

## Material missing predecessor: branching lifecycle and nonrollback state

Garfinkel and Rosenblum, *When Virtual Is Harder than Real* (HotOS 2005),
already observes that copy/checkpoint/rollback changes execution from a line to
a tree with simultaneously existing branches; that rollback can reactivate
accounts, passwords, keys, one-time values, and stale security state while an
external adversary cannot forget; and that security/history state should move
to a trusted virtualization layer independent of guest rollback. It even
discusses controlling replication and tracking identity/history. The current
bibliography does not cite it.

Primary source:
<https://www.usenix.org/legacy/event/hotos05/prelim_papers/garfinkel/garfinkel_html/index.html>

This source does not contain the paper's token ledger or Merge theorem, so it
is not a direct novelty kill. It is nevertheless a major framing omission
because it predates the conceptual problem statement and trusted-plane remedy
by roughly two decades. The agent-specific novelty must therefore reside in a
new theorem about semantic branch composition, not in “history becomes a tree”
or “keep security state outside the rollbackable snapshot.”

## Recent adjacent agent work

- ACRFence directly studies action replay and authority resurrection after
  agent restore and proposes a branch-tagged replay-or-fork effect log:
  <https://arxiv.org/abs/2603.20625>.
- Commit-Time Authorization makes branch eligibility, freshness, causal order,
  and effect binding checks at the commit boundary explicit:
  <https://arxiv.org/abs/2607.10487>.
- Cordon and Atomix cover lineage-aware transactions, staged effects,
  commit/abort, recovery, and deduplication:
  <https://arxiv.org/abs/2606.17573> and
  <https://arxiv.org/abs/2602.14849>.

The submission now distinguishes these works honestly. They do not create a
proof-to-paper mismatch, but they narrow the contribution to pre-Prepare
occurrence transport. That narrow contribution needs the missing necessity or
maximal-permissiveness result to survive a novelty attack.

