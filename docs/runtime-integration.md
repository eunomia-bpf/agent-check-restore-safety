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

## 3. Reinforcement learning and search workloads

The same principle applies to rollout-based agents, but the classification depends on what crosses the simulation boundary.

### Pure rollout

If rollouts use a hermetic simulator, no external observation escapes, and only one candidate action is eventually issued, candidates can remain pure with empty branch claims or use mutually exclusive conditional claims. A parent-held escrow is sufficient when no rollout needs an advance guarantee.

### Tool-using rollout

If a rollout queries a live API, reads a protected secret, contacts a human, consumes a quota, provisions a resource, or writes durable memory, its effect has escaped even if the trajectory later receives low reward. Environment reset or trajectory discard does not undo that effect. Promotion must occur at the tool boundary.

### Learning from many trajectories

If reward, observations, or artifacts from several rollouts enter a replay buffer, policy update, evaluation report, or long-term memory, those rollouts are co-durable with respect to that learned artifact. They cannot be treated as choose-one alternatives merely because only one environment action was selected. A policy update is a merge of provenance and can require joint privacy, licensing, human-feedback, or query-budget authority.

### Online and continual RL

Restoring a policy/optimizer checkpoint does not restore consumed data licenses, privacy budgets, reward-service quotas, human approvals, or changes made by deployed actions. Those facts belong to durable grant epochs and effect history. The proposed runtime contract can therefore cover search, best-of-N, tree-of-thought, online RL, self-improvement loops, and evaluation agents without making the theorem depend on LLM sampling.

This suggests a concrete RL rule: **a rollout may share conditional authority only while it is observationally sealed and its contribution to any learned or external artifact remains conditional on durable selection.**

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

## 6. Runtime algorithm: incremental contracts plus safe filters

A useful monitor must avoid enumerating every future set. The base implementation keeps:

- a structured choice/parallel contract tree;
- per-leaf typed conditional demand;
- durable typed demand and terminal claim IDs;
- cached componentwise `need` at every tree node;
- optional monotone feasibility guards introduced by support-changing operations.

For a pure structured tree, updates propagate from one leaf to the root:

- choice node: componentwise maximum;
- parallel node: componentwise sum.

Reserve, transfer, fork, replace, and local topology edits therefore take \(O(h|\mathcal K|)\) time for tree height \(h\). Merge constructs an explicit target node/policy and is admitted by the same recurrence.

Escape is handled before dispatch:

1. tentatively move claim \(c\) from its branch bundle to durable demand;
2. recompute the affected path and test direct admission;
3. if unsafe, return the exact additional compatible capacity and two lifecycle repairs:
   - **witnessed selection**, an always-representable conservative repair that durably conditions on the owner branch;
   - **safe-filter repair**, the exact abstract family of old configurations whose post-promotion load fits the grant;
4. durably install the chosen repair and promotion, then dispatch or record an uncertain send.

The pure choice/parallel grammar cannot always represent the exact safe filter. For example, promotion can leave every pair among three branches legal while forbidding their triple. The implementation must not hide this gap. The next theory iteration treats a lifecycle contract as a structured tree conjoined with typed threshold/forbidden-hyperedge guards. A concrete selected set can be checked in linear time; incremental compilation, explanation, and the complexity of maintaining advance guarantees are separate algorithmic results under development.

The API should return a certificate, not only allow/deny:

```text
admit
reject(stale_epoch | duplicate_claim | uncovered_effect)
repair(
  extra_capacity = vector,
  witnessed_selection = branch/path,
  exact_guard = typed threshold constraints,
  conflicting_claims = minimal explanation
)
```

This is valuable to an industrial runtime because it distinguishes policy failure from a recoverable lifecycle choice and can explain why “keep both,” “restore live,” or early tool dispatch consumed more authority than expected.

## 7. Minimal integration experiment

The paper needs one adapter per runtime, not a large benchmark:

1. register root/fork/subagent/worktree lineage in the durable ledger;
2. configure one typed one-use deployment or payment tool through an MCP proxy or blocking pre-tool hook;
3. run fixed histories for replace, live fork, exclusive best-of-N, parallel subagents, losing-branch escape, stale resume, and merge;
4. compare snapshot-local clone, split-all, delayed escrow, and lifecycle-aware admission;
5. report unsafe histories admitted, safe histories rejected, returned repair, and hook/ledger latency.

No test needs stochastic prompt behavior. The tool call, claim IDs, branch operations, and external responses should be deterministic. Product documentation establishes that the lifecycle shapes exist; the experiment establishes that the adapter observes the required facts and blocks the separating histories.
