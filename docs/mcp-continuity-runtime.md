# MCP continuity runtime

**Status:** real Codex 0.147 and provider-independent stdio boundary,
2026-08-16. Two independent Codex App Server processes restart the MCP child
over one host-durable journal joined to the real Control, binary History,
generation-bound Unix socket, and external payment service. Claude and the
cross-sandbox relay remain future work.

## Why this layer exists

An agent-level tool protocol and an OS sandbox solve different halves of the
problem. MCP describes a named operation and its business arguments, but it
does not prevent the agent from opening another network path. A sandbox can
block that bypass, but it cannot infer whether two encrypted requests are the
same payment or two intentional payments. The continuity runtime therefore
combines both:

1. an MCP server exposes only operator-declared business tools;
2. a supervisor supplies one stable execution identity;
3. a durable sidecar journal assigns each admitted call a monotonic sequence;
4. the resulting call identity enters the existing Operation/History gateway;
5. a credential-free Unix socket supplies the active sandbox identity and
   resolves the Operation kind to a provider contract; and
6. the sandbox has no direct provider route or credential.

The tool configuration contains a name, description, Operation kind, and a
small enforced argument schema. It cannot contain a URL, method, header, token,
or sandbox identity. Those fields come from the active Requirement and host
binding.

## Stable identity across failure

MCP JSON-RPC request IDs correlate protocol messages; they are not durable
business identities. The server never hashes arguments and guesses that two
identical calls are one action. Instead, it writes a `prepared` journal record
and fsyncs it before dispatch. The record binds:

```text
(supervisor execution ID, call sequence, JSON-RPC ID, protected request digest)
```

to one stable `call_id`. The protected digest covers the operator tool name,
its resolved Operation
kind, and canonical business arguments. Per-call MCP metadata is validated but
excluded because Codex legitimately changes it after restart. The runtime does
not merge calls merely because their arguments match: the supervisor execution
and ordered JSON-RPC identity remain part of admission.

One `completed` record stores the exact MCP response and
whether the execution became uncertain. Both record types form a SHA-256 chain
in a current-user 0600 file under a 0700 directory; the process holds an
exclusive lock. Reopening the sidecar returns a completed response without
dispatch, or resumes a prepared call with the same `call_id`. Changed request
meaning under that identity is rejected; changed transport metadata is not a
new external action.

The Unix executor makes at most two attempts with the exact same identity and
body. If the provider committed but its first response was lost, the second
attempt reaches the Operation already marked `unknown`; a queryable contract
observes the durable provider fact instead of dispatching the write again. If
no definitive outcome is available, the journal permanently fences new calls
from that execution. A model cannot turn uncertainty into a new payment by
issuing another tool call.

## Protocol surface

`runtime/cmd/mcp-operation-server` implements newline-delimited MCP stdio. It
supports the current `server/discover` path and the legacy `initialize` path,
plus `ping`, `tools/list`, and `tools/call`. Responses carry current MCP server
metadata, and list results are private and immediately stale. Tool inputs are
validated again inside the trusted server; advertised JSON Schema is not the
security boundary.

The current MCP specification deliberately uses a stateless core and says
stateful applications should carry explicit handles. That is useful for
scaling MCP, but a handle returned in a lost response cannot identify the
operation that produced it. The supervisor identity and pre-dispatch journal
fill that failure window without making the model manage idempotency keys.

## Current real execution

The integration tests use the production packages rather than a fake gateway:

- a real binary Control History and Requirement;
- a host-owned 0600 sandbox Unix endpoint with no bearer credential;
- a real independently durable payment service;
- a queryable, non-retry-safe Operation contract; and
- an MCP server restarted over its fsynced call journal.

The package-level test drives MCP bytes directly. The stronger public demo
launches two real Codex 0.147 App Server processes. Codex loads the server
through ordinary `[mcp_servers.continuity]` configuration, reports it ready,
and exposes `commit_effect` through its current code-mode MCP namespace. No
experimental client callback is used for the protected calls.

The payment service is deliberately non-idempotent. It commits the first
Operation and deliberately drops its response. The MCP executor repeats the
same `call_id`; History queries the
provider and settles that Operation without dispatching the write again. Codex
and its MCP child are then stopped. A second Codex process replays the same
model call with changed protocol metadata; the reopened journal returns the
exact prior result without reaching payment. A distinct second call commits
normally. The final evidence is three successful real Codex MCP items, eight
History events, two distinct Operations, two payment deliveries, and exactly
two durable commits. The first Operation records query settlement; the second
records direct settlement.

Run the public checks and build with:

```sh
make runtime-mcp-operation-check
make runtime-mcp-operation-demo
make runtime-mcp-operation-build
make runtime-codex-mcp-demo

# Check a retained run printed by the command above.
make runtime-codex-mcp-check \
  CODEX_MCP_EVIDENCE=/absolute/path/to/evidence
```

The binary requires four host/supervisor-owned inputs:

```text
mcp-operation-server \
  -config /operator/tools.json \
  -sandbox-socket /run/safe-change/sandbox.sock \
  -execution-id <supervisor-issued-id> \
  -journal /host-history/mcp-calls.jsonl
```

`runtime/deploy/mcp-operation/tools.json` is a credential-free example. The
journal must be outside any container or VM state that can be rolled back.

## Exact boundary and next work

This is not yet complete mediation for an arbitrary agent. It currently:

- implements stdio, not Streamable HTTP;
- supports a deliberately bounded flat argument schema;
- depends on the supervisor to mint and correctly resume execution identity;
- protects only tools routed through this server; and
- has not yet been invoked by a real Claude client; and
- starts the trusted journal-owning server as a Codex child in the current
  host demo, so that demo proves protocol and recovery behavior, not isolation
  from a malicious same-UID Agent process.

The next increment splits the boundary. A tiny untrusted stdio relay will run
beside Codex in the existing hardened Docker sandbox; a host-owned MCP process
will keep the journal, sandbox binding, and History connection outside the
Agent filesystem and restore domain. The relay will carry only MCP frames over
a private Unix socket. The same transport will cross Firecracker through the
existing host bridge, followed by a Claude runtime driver.

## External protocol references

- [MCP 2026-07-28 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [MCP stdio and Streamable HTTP transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [Codex MCP configuration](https://developers.openai.com/codex/mcp)
- [Codex App Server](https://developers.openai.com/codex/app-server)
- [Claude MCP integration](https://docs.anthropic.com/en/docs/mcp)
