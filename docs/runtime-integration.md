# Runtime Integration and Workload Coverage

**Status:** design grounded in official Claude Code/Codex documentation and
public trajectory schemas, plus a checked fixed-suite Codex App Server adapter
as of 2026-08-01.  The prototype verifies one isolated effect path; it is not a
product-wide security boundary.

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

The strongest integration is a client around the official [Codex App Server](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md), not transcript scraping.

- `thread/fork` creates a new thread ID, reports `forkedFromId`, can fork through a chosen turn, and emits `thread/started`. This supplies explicit lineage for a fresh branch epoch.
- forked threads retain a session-tree identifier, while root and child thread IDs remain distinct.
- thread resume, archive/delete, worktree lifecycle, subagents, and turn/item streams provide control-plane observations for lifecycle state.
- App Server exposes command, MCP-tool, file-change, and approval events to a custom client. Its experimental dynamic-tool flow sends the client `threadId`, `turnId`, `callId`, tool identity, and arguments and waits for the client response. That makes it the leading path for a prototype in which the adapter, rather than an advisory hook, owns protected dispatch.

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

## 7. Trace observability contract

Ordinary agent telemetry is useful but insufficient. SWE-chat records sessions,
checkpoints, commits, commands, tool calls, and tool results; OpenTelemetry
traces record times, response IDs, schemas, results, and errors; the Agent Data
Protocol standardizes call/result correlation. None of the inspected schemas
states which grant funded an operation, which branches may still become
durable together, whether a restored continuation replaces or coexists with
the old one, or whether an outward effect is prepared, dispatched, uncertain,
settled, or retried under the same durable operation identity.

The adapter should emit a compact replayable extension rather than retain model
text as security state. Every event carries an envelope
`(sequence_no, previous_hash, contract_hash, event_kind, body_hash)`, and the
canonical body is retained with it. The replay bundle begins with a canonical
genesis record containing issuer keys, grants, the root history, and the root
contract; later events are transition deltas, while `contract_hash` checks the
reconstructed result:

```text
HistoryEvent(
  history_id, parent_history_id, operation, source_boundary,
  branch_id, branch_epoch, active_or_retired,
  projection_hash, canonical_projection
)
AuthorityEvent(
  grant_id, grant_epoch, capacity,
  claim_id, source_claim_id, owner_branch, demand, status,
  support_hash, canonical_support, certificate_hash, canonical_certificate
)
EffectEvent(
  effect_id, claim_id, attempt_id, request_hash, idempotency_key,
  prepared | dispatched | uncertain | settled | aborted,
  sink_evidence_hash, canonical_sink_evidence, aggregate_outcome
)
```

Provider `callId` or `tool_call_id` remains a correlation field. The adapter
generates `effect_id` before dispatch and persists it across crash, resume,
retry, and fork; otherwise the runtime cannot distinguish a retry from a new
authority-consuming operation. `source_boundary` identifies the exact turn or
checkpoint prefix copied by Fork/Restore. The projection, support object,
contract certificate, and sink evidence are canonically serialized and either
inline or included in the immutable replay bundle; their hashes authenticate
the bytes but are not unresolved references into mutable runtime state. Replay
must reconstruct the initial and successor `LifecycleState` values plus their
abstract step labels without consulting model text or an unversioned external
pointer.

Append is crash-atomic to a ledger outside the checkpoint domain. Its durable
head `(sequence_no, event_hash)` is anchored in a non-rollbackable service such
as a remote append log, TPM monotonic state, or independently administered
transactional database. A hash chain without this trusted head detects interior
tampering but not truncation to an old valid prefix. Lifecycle/authority events
commit before a branch becomes active or a capability becomes usable. An
effect's `prepared` record commits before dispatch; dispatch uses the stable
idempotency key; and settlement records an authenticated receipt. The sink's
linearizable query returns authenticated evidence of either the stored outcome
or absence for that key. If a crash
occurs after remote success but before settlement, recovery queries an
idempotent/queryable sink by that key and appends the reconciled outcome. A
non-idempotent, non-queryable, or dishonest sink leaves this case ambiguous and
is explicitly outside the claimed refinement.

The fixed suite now establishes a bounded result: its O0/O1 projections each
retain three mixed-label fibers, while its O2 deltas reconstruct all 20 P3
states, labels, decisions, and durable anchors.  This does not establish the
general erasure or replay/refinement theorem.  That theorem must still show the
corresponding arbitrary concrete edges form a `SimulatedTrace` under complete
mediation, canonical certificate validation, the anchored durable head, and
the stated sink assumptions. Dataset frequency and “logging the checker state”
prove neither claim; an irredundancy or information lower bound is still needed
for a distinct observability contribution.

## 8. Minimal integration experiment

The paper first needs one dispatch-owning adapter, not a large benchmark. Codex
App Server supplies a native thread fork, a source-history boundary, and a
client-owned dynamic-tool dispatch. It does **not** natively supply all of the
paper's Restore/Merge meanings. The harness therefore owns this explicit
mapping:

- **exclusive/parallel Fork:** call the native thread-fork operation, then
  register the returned thread as a fresh branch epoch under an adapter-owned
  exclusive or parallel descriptor; the native verb alone does not choose the
  authority topology;
- **replacing Restore:** the design requires copying the selected source
  boundary into a fresh logical epoch and crash-atomically coupling source
  retirement to target activation.  The current fixed adapter performs these
  steps sequentially and leaves that crash window untested;
- **live Restore:** copy the same boundary into a fresh epoch while retaining
  the source as active;
- **Merge:** invoke an adapter API with the target histories, canonical
  serialized lineage projection/transfer certificate, contract hash, and
  artifact hashes. This is a prototype operation over Codex histories, not a
  claim that App Server exposes a native semantic Merge.

One persistent mock sink is a map keyed by stable `effect_id` and idempotency
key. Its linearizable query returns authenticated outcome or absence evidence.
Each effectful YAML case
names exactly one `dispatch_site` and one of four modes: `none`;
`before_dispatch` (after admission/Prepare, before the sink call);
`after_remote_success` (after the sink commits, before settlement append); or
`after_controller_commit` (after settlement append, before the tool reply).
Topology-only cases have no crash mode. This removes ambiguity about which of
several calls receives a fault.

The complete 20-case matrix is:

| Case | Base | Named site / operation | Crash mode | Required terminal state / decision |
|---|---|---|---|---|
| C01 | L1 | `e1.initial` | `none` | exactly one sink outcome and settled receipt for `e1`; reject fresh `e2` |
| C02 | L1 | `e1.initial` | `before_dispatch` | zero sink outcomes at crash; recovery reuses `e1`, dispatches once, settles exactly one outcome, then rejects fresh `e2` |
| C03 | L1 | `e1.initial` | `after_remote_success` | one sink outcome at crash; recovery queries by key and settles it without a second outcome, then rejects fresh `e2` |
| C04 | L1 | `e1.initial` | `after_controller_commit` | one outcome and settled receipt at crash; retry returns that receipt without redispatch, then rejects fresh `e2` |
| C05 | L10 | `left.e1.initial`; then `right.e2` | `none` | exactly one left outcome/receipt; reject right `e2` |
| C06 | L10 | `left.e1.initial`; then `right.e2` | `before_dispatch` | zero outcomes at crash; recover left `e1` to exactly one outcome/receipt; reject right `e2` |
| C07 | L10 | `left.e1.initial`; then `right.e2` | `after_remote_success` | reconcile the one left outcome without duplication; reject right `e2` |
| C08 | L10 | `left.e1.initial`; then `right.e2` | `after_controller_commit` | return the committed left receipt without redispatch; reject right `e2` |
| C09 | L13 | prepared `e.initial_after_revoke` | `none` | settle sealed `e` exactly once; reject fresh Prepare `e2` |
| C10 | L13 | prepared `e.initial_after_revoke` | `before_dispatch` | zero outcomes at crash; recover/dispatch sealed `e` to exactly one settlement; reject fresh `e2` |
| C11 | L13 | prepared `e.initial_after_revoke` | `after_remote_success` | reconcile the one sealed outcome without duplication; reject fresh `e2` |
| C12 | L13 | prepared `e.initial_after_revoke` | `after_controller_commit` | return the committed receipt without redispatch; reject fresh `e2` |
| C13 | L8 | replacing Restore, then fresh Reserve | no crash | accept Reserve |
| C14 | L8 | live Restore from the same bytes, then fresh Reserve | no crash | reject Reserve |
| C15 | choice Fork, `G=1` | one conditional unit Reserve in each child | no crash | accept both alternatives; never settle both |
| C16 | parallel shared grant lineage | `c1` and `c2` map to the same one-unit grant; Reserve in order | no crash | accept `c1` and reject `c2` |
| C17 | parent escrow, `G=1` | two pure children, select `c1`, transfer, Prepare | no crash | accept selected `c1` Prepare |
| C18 | parallel distinct grant lineages | transfer separate one-unit fragments `g1`/`g2` to `c1`/`c2` | no crash | accept both Reserves |
| C19 | certified Merge, `G=1` | retain one selected claim and retire alternatives | no crash | accept Merge |
| C20 | direct Merge, `G=1` | retain both alternative unit claims | no crash | reject Merge |

A baseline may reject a prerequisite before reaching the named final operation;
the runner records that earliest divergence as a safe or unsafe rejection
rather than fabricating a state the policy cannot reach. Every case is replayed
under the same two independent comparison axes:

**Observation ablations**

- `O0`: checkpoint/workspace state only; the monitor may use no session or
  durable event history;
- `O1`: `O0` plus provider session/call/result telemetry;
- `O2`: `O1` plus the trusted lifecycle, authority, and effect replay events
  above.

These ablations do not define an enforcement policy. They project the complete
oracle-labeled histories, not policy runs truncated by an earlier rejection.
Admission is a function of both an observed prefix and the proposed next
action, so the executable fiber key is

```text
K_i(prefix, action) = (α(O_i(prefix)), normalize(action)).
```

Here `α` replaces run-local thread/session/span/call/effect spellings by
namespace-specific first-occurrence names, preserves equality/alias structure
and event order, removes absolute timestamps/collection time, and hashes
canonical tool arguments after secret redaction. `normalize(action)` applies
the same renaming and fixes the operation kind, source role, typed demand,
binding, and same-versus-fresh operation relation. Time-based expiry is outside
the fixed suite; a later timed model must retain logical policy time. Raw IDs
or timestamps are never used as an equality key.

For each `Oi`, group controlled cases by `K_i` and count *mixed-label fibers*:
one key containing pre-states with different oracle decisions. The three
required witness fibers are:

| Witness | Paired prefixes and identical normalized next action | `O0`/`O1` relation | Opposite labels | `O2` discriminator |
|---|---|---|---|---|
| topology | C13 vs C14 before `Reserve(restored, fresh-claim, 1)` | same reconstructed bytes and alpha-normalized provider trace | accept vs reject | source epoch active/retired and replace/live lineage |
| authority | C16 vs C18 after `Reserve(c1,1)`, before `Reserve(c2,1)` | same parallel-fork/call trace; grant mapping erased | reject vs accept | shared grant versus distinct fragment lineages |
| effect | C02 vs C04 while the same App Server tool request is pending, before permission for physical `.attempt(e1,c1)` | same tool request with no result after alpha-normalization | C02 has a prepared ticket and admits Dispatch; C04 is already settled, denies a new attempt, and returns the cached receipt as a zero-outcome stutter | prepared ticket versus settled receipt |

Each paired YAML case issues the named admission request as a non-mutating
probe, records the oracle and monitor labels, and then follows its required
terminal recovery path. Thus the C02/C04 probe compares permission to perform
the same physical attempt without replacing C02's mandatory eventual
settlement or C04's cached reply. The earlier C02/C03 `FinalizeAbort` proposal
is retired: the current abstract Settle rule permits cancellation from an
uncertain phase and has no authenticated-absence premise, so that pair would
not witness the existing LTS.

`O0` and `O1` are expected to contain such fibers, so decoder ambiguity,
abstention, and wrong decisions are results rather than run failures. `O2` must
have no mixed-label fiber in the suite, reconstruct the genesis
`LifecycleState` plus every abstract label/successor, and reproduce every
checker decision.  The retained checker separately joins that controller
chain to App Server, fault, and sink evidence; this fixed-suite composite audit
does not itself construct the theorem's full `SimulatedTrace`.

**Admission policies**

The YAML supplies typed operation streams and stable logical effect names to
every policy, but no expected decision.  The oracle remains a separate
checker-only fixture.  For fault-comparison fairness all policies use the same
durable effect state machine and sink: Prepare and stable idempotency precede
dispatch; recovery queries uncertain attempts; a prepared ticket survives
revocation and may settle once.  They differ in authority/topology admission.
`P0` deliberately lacks correlated future accounting; it is a null admission
control, not a faithful end-to-end implementation of an uninstrumented agent.

| Policy | Complete transition rule for the fixed suite |
|---|---|
| `P0 workspace/topology-local` | Ignore correlated authority solvency when admitting Reserve/Restore/Fork/Merge, while retaining the common durable ticket/receipt harness solely so all policies face the same worker faults and sink. The live JSON-RPC frontend retains the actual pending App Server `callId`, which P0 uses as its physical sink key; the harness never synthesizes a replacement. P0 therefore tests unsafe authority resurrection/co-durability, not duplicate behavior after frontend/App Server loss. |
| `P1 split-all` | At any exclusive or parallel Fork with remaining vector `R` and children ordered by branch ID, each coordinate uses `divmod(R[k], n)`: every child gets the quotient and the first remainder children get one extra. Replace moves the source budget to the fresh epoch; live Restore applies the same deterministic split to the source and copy. Merge retires every input and transfers the sum of their unspent, disjoint local budgets; a Merge retaining a live input is rejected. Revoke closes all local budgets for new Prepare; the shared prepared-ticket rule still permits one settlement. |
| `P2 parent-escrow` | Fork gives children zero protected capacity and leaves the remainder at the parent. Pure computation is allowed; `Select(c)` atomically retires siblings and transfers capacity to exactly one child before Prepare. Replace moves a selected branch's allocation or copies an unselected pure candidate; live Restore returns unprepared capacity to escrow and requires a new selection while existing prepared tickets remain sealed. Merge is accepted only as selection of one authority-bearing lineage while retiring the others; combining several authority-bearing lineages is rejected. Revoke/retry use the shared ticket rule. |
| `P3 authority-continuity` | For this bounded suite, retain the explicit correlated frontier, apply canonical Fork/Restore, validate the fixed C19 Merge projection/claim map or perform direct target admission, and require a durable stable ticket before every protected dispatch. Revoke, Retry, Crash, and settlement follow the checked lifecycle/effect rules. The compact rectangular fast path is not implemented here. |

The independent oracle encodes the existing litmus expectations: L1 keeps the
previous durable charge and rejects fresh duplicate authority; L8 admits fresh
Reserve after replacing Restore and rejects the equal-byte live case; L10
rejects the second jointly durable one-use effect even though both transactions
are individually valid; and L13 lets a prepared operation settle once after
revocation while rejecting
a fresh Prepare and treating retry as the same operation. The sink oracle
additionally checks one aggregate outcome per `effect_id` and reconciles every
success-before-commit crash from its receipt. The oracle reads only the suite
specification and sink snapshots, not the controller's verdict.

The adapter reproducibility interface is implemented:

```bash
adapter_run_dir="$(mktemp -d)"
python -m adapter.codex_litmus \
  --suite adapter/litmus.yaml \
  --runtime-lock adapter/runtime-lock.json \
  --raw-dir "$adapter_run_dir/raw" \
  --output "$adapter_run_dir/litmus.json" \
  --workspace .
python -m adapter.check_results \
  --suite adapter/litmus.yaml \
  --oracle adapter/oracle.yaml \
  --input "$adapter_run_dir/litmus.json" \
  --output "$adapter_run_dir/check.json"
```

`runtime-lock.json` records the App Server version, binary/schema hashes,
protocol feature flags, and host environment.  Both commands exit zero on the
retained revision-2 run.  Across 80 policy runs, P3 matches 89/89 frozen
decisions, all 20 logs replay, and no unsafe request or duplicate aggregate
effect is admitted.  Raw JSONL matches 44 dynamic-tool calls and 187 native
forks: 80 per-run setup roots and 107 accepted lifecycle materializations (80
fork children, 24 restore copies, and three merge targets).  Logical ancestry
remains adapter metadata.  All 33 hard worker crashes recover in distinct
processes.  O0/O1 each retain the three required mixed-label fibers and O2
retains none.  P0 has
11 unsafe accepts; P1/P2 have respectively four/nine safe rejects and no unsafe
accept.  Exact raw artifacts and the rejected first pilot are retained under
`adapter/results/` and the Step 0004 directory.

This result does not make the future trace census complete, measure ledger
latency, or establish native Codex Restore/Merge semantics.  Claude Code
through a mandatory MCP proxy remains a later portability check, not a second
unfinished prototype.
