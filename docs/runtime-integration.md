# Runtime Integration and Workload Coverage

**Status:** design grounded in official Claude Code and Codex documentation checked on 2026-07-31. Product hooks are integration evidence, not yet an implemented or verified security boundary.

## 1. Industrial principle

The memorable rule is:

> **Authority follows durable support, not copied state.**

It has three operational consequences:

1. **Copying computation does not copy authority.** A checkpoint, conversation fork, worktree, or subagent receives a fresh branch epoch. Existing claims must remain in escrow, transfer once, split explicitly, or be re-reserved.
2. **Discarding computation does not discard history.** Abort, rewind, worktree deletion, or losing selection can cancel only effects still held behind a trusted gate. Dispatched, disclosed, and uncertain effects remain charged.
3. **Merging computation does not merge authorization.** Combining files, messages, or learned artifacts can change which commitments contribute together. Claims and grants are re-admitted under an explicit target lifecycle policy.

Equivalently: a runtime may share one bounded grant among alternative futures only while it can durably enforce their exclusivity and keep all corresponding effects conditional. Before any effect escapes, it must either prove the promoted contract solvent, obtain authority, weaken tentative promises, or durably restrict the future family.

## 2. Lifecycle coverage

The model covers C/R and fork as instances of support transformation, not as special cases:

| Runtime operation | Reconstructable state | Durable lifecycle meaning | Authority rule |
|---|---|---|---|
| Checkpoint | records a version of local computation | no new continuation | never snapshot the authoritative ledger |
| Resume same continuation | reloads context | same branch epoch remains current | consult current epoch and durable history |
| Restore-replace | reconstructs an old version | old epoch is tombstoned before a fresh replacement is eligible | transfer a binding-preserving claim once; never copy it |
| Restore-live / session fork | reconstructs the same version | old and new continuations remain eligible | insert a parallel clone in the original context and re-admit commitments |
| Exclusive fork / best-of-N | copies candidates | controller guarantees at most one retained outcome | conditional claims may share capacity while effects remain staged |
| Parallel subagents | copies/delegates work | several descendants may contribute | demands add; claim identity cannot be duplicated |
| Select / abort | removes possible outcomes | losing epochs are durably closed | cancel only tentative claims; durable/uncertain claims remain |
| Escape / tool dispatch | may leave local state unchanged | an effect becomes observable in every subsequent history | promote before dispatch and install an admitted residual contract |
| Merge / handoff | combines values or provenance | previously alternative outcomes may become co-durable | supply a target policy and re-admit transferred claims |
| Revoke | may leave stale references in snapshots | closes a grant epoch monotonically | restored references remain stale; consumption remains historical |

The theory does not assume that a product verb has one meaning. “Restore” is replace only if the old continuation is durably fenced. “Fork” is exclusive only if the controller guarantees one winner. A Git worktree gives file isolation but says nothing about external authority.

## 3. Prospective reinforcement-learning mapping

The calculus contains no reinforcement-learning primitive and does not prove reward, policy-update, privacy-accounting, licensing, or provenance correctness. An adapter may model hermetic choose-one rollouts as exclusive only while no protected effect escapes before selection. A parent escrow suffices when branches need no advance guarantee.

For a tool-using rollout, the adapter may assign finite-vector claims to mediated API calls, human requests, quota uses, or durable writes. Resetting the environment then cannot erase those supplied claims. If several rollout artifacts are retained, the adapter must supply a trusted merge projection describing which lineages remain represented. The authority results apply to those declared claims and projections; establishing that a replay buffer or policy update has the asserted provenance remains a separate research problem.

## 4. Codex integration surface

The strongest integration is a client around the official [Codex App Server](https://learn.chatgpt.com/docs/app-server.md), not transcript scraping.

- `thread/fork` creates a new thread ID, reports `forkedFromId`, can fork through a chosen turn, and emits `thread/started`. This supplies explicit lineage for a fresh branch epoch.
- forked threads retain a session-tree identifier, while root and child thread IDs remain distinct.
- thread resume, archive/delete, worktree lifecycle, subagents, and turn/item streams provide control-plane observations for lifecycle state.
- App Server exposes command, MCP-tool, file-change, and approval events to a custom client.

For an existing CLI/app deployment, official [Codex hooks](https://learn.chatgpt.com/docs/hooks.md) provide a narrower prototype surface:

- `SessionStart` distinguishes startup/resume/clear/compact;
- `SubagentStart` and `SubagentStop` expose subagent IDs;
- `PreToolUse` can inspect, deny, or rewrite Bash, `apply_patch`, MCP calls, and most local function tools;
- `PostToolUse` can record outcomes but cannot undo a completed side effect;
- managed hooks can be enforced by enterprise configuration.

The hook documentation also states a decisive limitation: hosted tools such as web search are not covered and specialized tool paths can opt out. Project hooks are therefore useful for a prototype and fixed litmus tests, but they are not a complete mediation theorem. A production TCB needs either an App Server client that owns approvals, a mandatory MCP/tool proxy, OS/network mediation, or product-level integration that can attest complete effect coverage.

Codex also supports chat `/fork`, ephemeral side chats, subagents, and Git worktrees. These are concrete examples of distinct lifecycle dimensions: transcript lineage, agent concurrency, and filesystem isolation do not automatically coincide.

## 5. Claude Code integration surface

Claude Code provides particularly direct separating examples in its official documentation:

- [Checkpointing](https://code.claude.com/docs/en/checkpointing) can restore code and conversation independently. It does not track Bash changes or general external changes, and most background/subagent edits are not restored with the main session.
- [Sessions](https://code.claude.com/docs/en/sessions) can be resumed or forked. A fork gets a new session ID while preserving the original; in-process branching and separate-process `--fork-session` differ in which temporary permissions they inherit.
- [Hooks](https://code.claude.com/docs/en/hooks) expose `PreToolUse`, `PostToolUse`, `SessionStart`, `SubagentStart/Stop`, and `WorktreeCreate/Remove`. `PreToolUse` can block a tool before execution; `PostToolUse` cannot undo it.
- The [Agent SDK checkpoint API](https://code.claude.com/docs/en/agent-sdk/file-checkpointing) exposes checkpoint and session identifiers, but file rewind still covers only the listed editing tools.

A prototype can register each session/subagent/worktree as a fresh branch epoch and place a deterministic hook in front of high-impact tool and MCP calls. Precise session-fork and rewind semantics should be captured by an SDK/CLI wrapper rather than inferred from mutable transcript JSON. As with Codex, complete mediation requires controlling every effect path; hook availability alone does not prove that property.

## 6. Runtime algorithm: certificate-checked authority support

A useful monitor must avoid enumerating every future set. The implementation keeps:

- a structured choice/parallel contract tree;
- per-leaf typed conditional demand;
- durable typed demand and terminal claim IDs;
- cached componentwise `need` at every tree node;
- frozen monotone, zero-preserving threshold rows introduced by support-changing operations;
- explicit lineage-predicate circuits and a contract state hash;
- one-shot prepared/inflight/uncertain tickets keyed by stable operation IDs, plus receipts.

For a pure structured tree, updates propagate from one leaf to the root:

- choice node: componentwise maximum;
- parallel node: componentwise sum.

Reserve on an unguarded tree takes \(O(h|\mathcal K|)\) time for tree height \(h\). Claim-preserving fork, replace, live restore, and some merges instead take a proof path: the adapter preserves \(G,D,J,R\), terminal history, and epoch closure; it supplies a monotone, zero-preserving projection plus a fragment-conserving tentative-claim map; and the controller checks that every target load is dominated by its source image. Guarded cases may need a global solver to produce a proof object, but only the sound proof checker belongs in the trusted base. A merge without simulation needs full target admission.

Before distributing branch-local capabilities, the monitor tests residual factorization. If the all-headrooms corner satisfies every permitted configuration, the residual is exactly the Cartesian product of local headroom budgets and branches can check Reserve independently. If not, copying those local maxima would be unsound: the runtime retains the correlated coordinator/parent escrow, conservatively shrinks at least one delegated budget, or restricts the lifecycle contract. A choice-to-parallel live restore can cross this boundary even when no branch-local balance changes.

Escape is handled before dispatch:

1. verify that the owner, claim, epoch, binding, and effect path are current;
2. construct the promoted target and test the plain fast path;
3. if plain promotion is unsafe, return the exact additional compatible capacity and two lifecycle repairs:
   - **witnessed selection**, an always-representable conservative repair that durably conditions on the owner branch;
   - **frozen threshold repair**, one compact row whose models are exactly the old configurations whose post-promotion load fits the grant;
4. identify unsupported owners and removed maximal configurations/correlation obligations and report them as induced semantic changes;
5. atomically install the chosen lifecycle restriction, promotion, one prepared ticket per stable effect operation ID, and state hash;
6. only then Dispatch; Crash may retain the ticket as uncertain, and Retry emits another attempt with the same stable ID and claim.

The pure choice/parallel grammar cannot always represent the exact repair. For example, promotion can leave every pair among three branches legal while forbidding their triple. The frozen row is therefore part of the durable contract, not a transient solver fact. Its coefficients record the load at repair time; they never point to mutable current reservations. Later fork/restore/merge operations transport the row through monotone, zero-preserving lineage substitution; predicate-circuit size is part of the representation. Relaxing a row after capacity acquisition or claim withdrawal may be authority-safe, but is a separate, explicitly admitted topology expansion under the no-silent-expansion audit rule.

Checking whether one concrete retained set satisfies the tree and sparse rows is linear in the stored coefficient-plus-predicate-circuit representation. Universal admission of a new unrestricted promise can nevertheless be coNP-complete: an all-parallel tree plus one scalar row already contains 0--1 knapsack. The implementation uses cotree dynamic programming while no guard is present, ZDD/residual-capacity compilation for small integer quotas, and an incremental pseudo-Boolean solver for the general compact contract, failing closed on timeout.

Escape has a useful fail-safe asymmetry: constructing the exact frozen restriction is linear in the branch-by-coordinate matrix and does not require solving the universal optimization problem. The expensive step is deciding that no restriction is needed, optimizing cancellations, or proving support for every retained promise.

The API should return a certificate, not only allow/deny:

```text
Accept(state_hash, certificate)
Reject(reason, violating_configuration, coordinate, deficit)
AcceptWithRestriction(
  state_hash,
  frozen_rows,
  support_witnesses,
  induced_cancellations,
  removed_maximal_configurations,
  alternatives
)
```

The explanation can contain a checkable violating configuration without promising a globally minimum cancellation set. This distinguishes policy failure from a recoverable lifecycle choice and explains why “keep both,” “restore live,” or early tool dispatch consumed more authority than expected.

Concurrent escape requests are either prepared atomically as one batch or grouped by owner. Every owner-group ordering is executable exactly when every promoted owner remains supported by the final repaired contract; otherwise at least one ordering is disabled. A controller may validate a particular safe order, coordinate or defer cleanup, or atomically seal the fixed batch. The abstract filters commute, but that algebraic fact alone does not authorize a dispatch from a branch cleanup already removed.

## 7. Minimal integration experiment

The paper needs one adapter per runtime, not a large benchmark:

1. register root/fork/subagent/worktree lineage in the durable ledger;
2. configure one typed one-use deployment or payment tool through an MCP proxy or blocking pre-tool hook;
3. run fixed histories for replace, live fork, exclusive best-of-N, parallel subagents, losing-branch escape, stale resume, and merge;
4. compare snapshot-local clone, split-all, delayed escrow, and lifecycle-aware admission;
5. report unsafe histories admitted, safe histories rejected, returned repair, and hook/ledger latency.

No test needs stochastic prompt behavior. The tool call, claim IDs, branch operations, and external responses should be deterministic. Product documentation establishes that the lifecycle shapes exist; the experiment establishes that the adapter observes the required facts and blocks the separating histories.
