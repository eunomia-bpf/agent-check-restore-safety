# Experiment Plan: RQ4 deployable boundary across Agent runtimes

## Research Question

- RQ exactly as written in the repository evaluation contract: “RQ4: Is there
  a deployable algorithmic boundary?”
- Specific uncertainty tested here: whether the host-owned MCP and Operation
  boundary works below an unmodified official Claude Code process, rather than
  depending on Codex App Server callbacks.
- Why the answer matters: a Codex-only seam cannot support the intended
  runtime claim or a transparent community interface shared by Agent runtimes.

## Paper-Value Admission

- Planned role: supporting.
- Largest credible paper story this experiment could unlock: the same durable
  external-operation boundary survives replacement of two independently
  implemented real Agent runtimes without modifying either executable.
- Strongest uncertainty addressed: Claude may renumber or reshape MCP calls,
  persist hidden session state, require interactive approval, or terminate its
  stdio child in a way that prevents host completion and replay.
- Independent evidence beyond existing runs: official Claude Code protocol,
  process-group, config, MCP, and raw stream behavior. Existing Codex and
  Firecracker evidence cannot establish any of these facts.
- The result is not tautological because the trusted host sees only MCP bytes;
  no producer code controls Claude's request IDs, process tree, or stream.
- Paper decision if positive: retain provider-independent Agent-process
  portability as supporting RQ4 evidence and proceed to Claude inside the
  existing Firecracker cell.
- Paper decision if contradictory, mixed, or inconclusive: describe the seam
  as Codex-specific until a different explicit Claude identity mechanism is
  implemented; do not infer whole-runtime portability.
- Best alternative: immediate Claude-in-Firecracker replacement. This smaller
  run has higher current diagnostic value because it isolates the vendor MCP
  contract before VM transport and snapshot state can confound a failure. It
  is not a substitute for that next whole-VM experiment.

## Expected And Alternative Outcomes

- Expected answer: a host process can finish an in-flight protected call after
  the complete Claude process group is killed, and a clean Claude process can
  replay that exact response before making the next call.
- Strongest competing explanation: success in Codex relied on Codex-specific
  stable identifiers or process behavior absent from Claude.
- Contradiction: another A provider delivery, no host journal completion after
  process loss, a different replay identity, interactive approval, or failure
  of the replacement Claude process to reach `DONE`.

## Published Precedent And Real Assets

- Closest published protocol: Anthropic's official Claude Code headless CLI,
  MCP configuration, and signed-release verification documentation.
- Official asset and version: Claude Code 2.1.233, Linux x64 native binary.
- Reused components: the unchanged Claude executable and MCP stdio protocol;
  the already tested host Control, History, MCP host, relay, and payment
  binaries.
- Custom glue: a deterministic local Anthropic Messages endpoint, process-loss
  supervisor, evidence producer, and independent evidence checker.

## Comparison

- Proposed system: long-lived host MCP journal plus the existing sandbox-bound
  Operation gateway.
- Main baselines: none. This is a qualitative portability/correctness check,
  not a superiority claim. Prior Codex evidence is a different frontend cell,
  not a baseline.
- Control: a deliberately non-idempotent provider held after A commits;
  distinct private config directories and session IDs for the two processes.
- Fairness: the model output is deterministic in both lifetimes; the host does
  not rewrite Claude's MCP bytes or select its JSON-RPC identity.

## Workloads And Metrics

- Workload: commit A, commit B, return `DONE` through one protected MCP tool.
- Primary correctness facts: A provider deliveries = 1, B deliveries = 1,
  commits = 2, Operations = 2, source exit = `SIGKILL`, replacement exit = 0.
- Ground truth: provider durability file, binary History and external head,
  hash-chained MCP journal, raw Claude streams, model requests, and Linux
  `/proc` process identities.
- Repetitions: one final deterministic correctness run after one real
  preflight. No timing distribution or performance claim is made.

## Planned Runs

| Run group | Role | Workload | System/method | Repetitions | Decision consequence |
|---|---|---|---|---:|---|
| preflight | control | A/B process replacement | official Claude + host boundary | 1 | establish real protocol engagement |
| final | proposed | held A, `SIGKILL`, clean replay, B | pinned official Claude + independently checked host evidence | 1 | supporting portability evidence or contradiction |

## Execution

- Authoritative workflow: `make runtime-claude-mcp-demo` followed by
  `make runtime-claude-mcp-check`.
- Real preflight: `/tmp/claude-mcp-real-v2.w2nqzu`.
- Full completion rule: signed binary verification passes; both processes
  terminate with the planned statuses; the independent checker returns
  `valid=true`; all unit and runtime regressions pass.
- Raw-result path:
  `docs/tmp/bootstrap/step-0019-20260817T010000Z/experiment-claude-process-continuity/raw/`.
- Recovery: a failed run remains retained and a fresh empty directory is used
  after a bounded implementation repair.

## Interpretation

- Positive: supporting evidence that the process-level boundary is not tied to
  Codex, with no whole-VM or complete-mediation claim.
- Negative: a bounded Claude frontend incompatibility; redesign the explicit
  call-identity seam before VM integration.
- Mixed or inconclusive: retain raw evidence and do not add portability.
- Target paper figure or table: none until consolidated into the broader RQ4
  systems matrix.

## Reproducibility Notes

- Software: Claude Code 2.1.233, exact signed manifest and binary hashes in
  `runtime/deploy/claude-code/assets.lock.json`.
- Config: `--bare`, headless stream JSON, strict explicit MCP file, separate
  private config directories, local deterministic model endpoint.
- Known deviation: the model endpoint is a fixture, so this tests the real
  Agent runtime and MCP client but not a live Anthropic model.
