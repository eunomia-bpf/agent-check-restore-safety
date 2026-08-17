# Real Claude Code process continuity

This slice shows that the host boundary is an Agent-runtime interface rather
than a Codex-specific callback. It runs the official Claude Code 2.1.233 Linux
binary twice against one long-lived host MCP server and one deliberately
non-idempotent provider. Claude Code itself is unmodified.

## Boundary

Claude receives one ordinary stdio MCP configuration. The stdio child is an
untrusted byte relay: it contains no provider address, tool mapping, History,
credential, sandbox identity, or recovery state. A host-owned MCP process keeps
the tool definition and an fsynced call journal. It reaches the existing
credential-free sandbox socket, whose binding selects the domain, allowed
Operation kind, active Rule, and provider route.

```text
Claude Code process group                     trusted host

claude -> stdio relay -> private Unix socket -> MCP host + call journal
                                                    |
                                         sandbox Operation socket
                                                    |
                                        History / Rule / provider
```

The same host components and journal format are used by the Codex and
Firecracker paths. Only the vendor-facing process launcher and raw protocol
evidence differ.

## Exact run

The fixed workload requests `effect-A`, then `effect-B`, then `DONE`. A local
Messages API fixture determines these model outputs; it replaces only the
model endpoint, not Claude Code or its MCP implementation.

1. The first Claude process starts with `--bare`, a private empty config
   directory, strict explicit MCP configuration, and only the protected MCP
   tool pre-approved.
2. It calls `effect-A`. The provider durably commits A and holds the response.
   The MCP journal contains only A's synced `prepared` record.
3. The supervisor sends `SIGKILL` to the first Claude session and therefore to
   its stdio relay child. The host MCP process is outside that process group.
4. The provider response is released. The host completes A in History and in
   its journal even though no Claude process can receive that response.
5. A second Claude process starts with a different session ID and a separate
   empty config directory. Its repeated A request has the same execution-local
   JSON-RPC identity and protected-request digest, so the host returns A's
   exact journaled response without another provider delivery.
6. The second process calls B. The provider commits it once, Claude receives
   both results, and the process exits zero after returning `DONE`.

The retained execution has two provider deliveries and two provider commits:
one for A and one for B. There is no second A delivery. History has seven
events: one Rule-and-binding cutover and prepare/dispatch/succeed for each
Operation.

## Reproduce

The fetch target downloads the pinned official binary without installing it
globally. It verifies Anthropic's published release-key fingerprint, detached
manifest signature, signed `linux-x64` manifest entry, file size, SHA-256, and
version output. The procedure follows the official
[Claude Code integrity instructions](https://code.claude.com/docs/en/setup).

```sh
make runtime-claude-fetch

evidence=$(mktemp -d /tmp/claude-mcp-evidence.XXXXXX)
workspace=$(mktemp -d /tmp/claude-mcp-workspace.XXXXXX)
make runtime-claude-mcp-demo \
  CLAUDE_MCP_DEMO_ARGS="--workspace $workspace --evidence-dir $evidence"

make runtime-claude-mcp-check CLAUDE_MCP_EVIDENCE="$evidence"
```

The demo uses the documented Claude Code
[headless CLI](https://code.claude.com/docs/en/headless) and
[MCP configuration](https://code.claude.com/docs/en/mcp). It requires neither
an Anthropic account nor a user Claude configuration because the model endpoint
is loopback and deterministic.

The standalone checker uses only the Python standard library and shares no
producer code. It verifies:

- the pinned Claude binary and committed release lock;
- exact launch arguments, distinct sessions, `SIGKILL` and exit-zero statuses;
- live `/proc` executable identities for both Claude processes and both relay
  children, including process group and parent relations;
- raw Claude streams showing that the first process received no tool result
  and the second received A, B, and `DONE`;
- all four raw Messages requests and their placement inside the two process
  lifetimes;
- the hash-chained MCP journal, binary History, external head anchor, and
  provider facts; and
- separate private config trees, removal of the runtime admin token, and
  absence of the fixture API credential from retained evidence.

## What this establishes

This is real vendor portability and real process-loss evidence. It establishes
that one host continuity boundary can sit below both Claude Code and Codex
without patching either executable, and that the Agent process and its MCP
stdio child can be disposable while an external Operation remains durable.

It is a correctness run, not a throughput result. The source process is killed,
but it is not yet inside Firecracker. Built-in Bash/Edit/Read tools remain
visible to Claude, although this workload uses only the protected MCP tool; a
production claim requires routing every protected effect through the boundary.
The deterministic model fixture makes the second process reproduce the same
ordered MCP request. General semantic reconciliation when a replacement Agent
chooses a different action sequence remains an open runtime problem. The next
vertical slice should put this exact Claude process contract inside the
existing Firecracker cell and replace the complete VMM while preserving the
same host journal.
