# MCP continuity runtime

**Status:** real Codex 0.147 across both hardened Docker and real Firecracker
boundaries, 2026-08-16. Untrusted stdio relays connect to one long-lived
trusted host that retains the journal and joins it to the real Control, binary
History, generation-bound Unix socket, and external payment service. The
Claude integration remains future work.

## Why this layer exists

An agent-level tool protocol and an OS sandbox solve different halves of the
problem. MCP describes a named operation and its business arguments, but it
does not prevent the agent from opening another network path. A sandbox can
block that bypass, but it cannot infer whether two encrypted requests are the
same payment or two intentional payments. The continuity runtime therefore
combines both:

1. an untrusted stdio relay inside the Agent restore domain carries only MCP
   frames;
2. a trusted host outside that domain exposes only operator-declared business
   tools and retains one stable supervisor execution identity;
3. a durable host journal assigns each admitted call a monotonic sequence;
4. the resulting call identity enters the existing Operation/History gateway;
5. a separate credential-free Unix socket supplies the active sandbox identity and
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

The shared protocol implementation supports the current `server/discover`
path and the legacy `initialize` path, plus `ping`, `tools/list`, and
`tools/call`. `runtime/cmd/mcp-operation-server` exposes it directly over
newline-delimited stdio for compatibility. The stronger path keeps it in
`mcp-operation-host`; `mcp-operation-relay` only copies bytes between stdio and
a private same-UID Unix socket. The host authenticates each relay with
`SO_PEERCRED`, may serve overlapping relay lifetimes, and serializes every
protected request through one shared server and journal order. Responses carry
current MCP server metadata, and list results are private and immediately
stale. Tool inputs are validated again inside the trusted host; advertised
JSON Schema is not the security boundary.

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
- one trusted MCP host retained across two untrusted relay processes.

The package-level test drives MCP bytes through two replacement relays. The
host public demo launches two real Codex 0.147 App Server processes. The
stronger Docker demo launches the same App Server twice in distinct container
processes. Codex loads only the relay through ordinary
`[mcp_servers.continuity]` configuration, reports it ready, and exposes
`commit_effect` through its current code-mode MCP namespace. The trusted host
is a separate, longer-lived process. No experimental client callback is used
for the protected calls.

The payment service is deliberately non-idempotent. It commits the first
Operation and deliberately drops its response. The MCP executor repeats the
same `call_id`; History queries the
provider and settles that Operation without dispatching the write again. Codex
and its relay are then stopped while the host remains alive. A second Codex
process and relay replay the same model call with changed protocol metadata;
the retained host returns the exact prior result without reaching payment. A
distinct second call commits normally. The offline checker reconstructs both
raw Codex commands and proves that they contain only the relay and its socket,
not the host configuration, journal, execution identity, or sandbox endpoint.
It also joins two distinct relay peer PIDs to one host log. The final evidence
is three successful real Codex MCP items, eight History events, two distinct
Operations, two payment deliveries, and exactly two durable commits. The first
Operation records query settlement; the second records direct settlement.

In Docker mode, the checker additionally replays raw inspection records for
both container lifetimes. Each container has a read-only root filesystem, all
capabilities dropped, `no-new-privileges`, a private internal network, and
exactly five mounts: read-only workspace, staged Codex bundle, relay bundle,
and host-socket directory, plus an empty writable Codex home. The staged Codex
bundle is current-user read-only; the relay and socket are each the sole entry
in a 0700 source directory. Direct probes from both running containers to the
payment port through container loopback and the Docker gateway fail. The model
fixture alone binds the private gateway, while payment remains on host
loopback.

The Firecracker target runs the same guest relay at fixed loopback port 7002.
Guest PID 1 is the only process allowed to translate that port into a
generation-bound host stream; the seccomp-confined Codex domain has no direct
vsock authority. The trusted MCP host, journal, History, and provider remain
outside the snapshot. In the checked KVM run, Codex completed A, the runtime
snapshotted and replaced the entire VMM, and a new MCP session replayed A
before submitting B. The replay returned the exact cached response without a
provider delivery. The run retained three relay lifetimes, three successful
Codex MCP completions, two History Operations, and exactly two commits at a
non-idempotent provider. Separate Firecracker and continuity checkers rebuilt
the result from the retained records.

Run the public checks and build with:

```sh
make runtime-mcp-operation-check
make runtime-mcp-operation-demo
make runtime-mcp-operation-build
make runtime-codex-mcp-demo
make runtime-codex-mcp-docker-demo
make runtime-firecracker-codex-mcp-demo
make runtime-firecracker-codex-mcp-inflight-demo \
  FIRECRACKER_CODEX_MCP_INFLIGHT_DEMO_ARGS="<the same pinned artifact arguments>"

# Check a retained run printed by the command above.
make runtime-codex-mcp-check \
  CODEX_MCP_EVIDENCE=/absolute/path/to/evidence

# Check retained Firecracker evidence.
make runtime-firecracker-codex-mcp-check \
  FIRECRACKER_CODEX_MCP_EVIDENCE=/absolute/path/to/combined \
  FIRECRACKER_CODEX_PAYLOAD=/absolute/path/to/codex.squashfs \
  FIRECRACKER_CODEX_PAYLOAD_RESULT=/absolute/path/to/payload.json \
  FIRECRACKER_CODEX_RUNNER=/absolute/path/to/firecracker-codex-shim
```

The in-flight target deliberately tests the harder boundary. The provider
fsyncs A while Codex is still waiting, then Firecracker takes a full snapshot.
The restored live vsock transport is not assumed correct: that VM is allowed
to fail closed, while the host-owned journal remains authoritative. A cold
replacement microVM replays the exact A response and advances to B. The
checker joins both VM attempts to one journal, one History chain, and exactly
two non-idempotent provider commits.

The compatibility binary requires four host/supervisor-owned inputs:

```text
mcp-operation-server \
  -config /operator/tools.json \
  -sandbox-socket /run/safe-change/sandbox.sock \
  -execution-id <supervisor-issued-id> \
  -journal /host-history/mcp-calls.jsonl
```

`runtime/deploy/mcp-operation/tools.json` is a credential-free example. The
journal must be outside any container or VM state that can be rolled back.
The split deployment instead keeps those inputs on the host:

```text
mcp-operation-host \
  -config /operator/tools.json \
  -sandbox-socket /run/safe-change/sandbox.sock \
  -listen-socket /run/safe-change/relay/mcp.sock \
  -execution-id <supervisor-issued-id> \
  -journal /host-history/mcp-calls.jsonl

mcp-operation-relay -socket /run/safe-change/relay/mcp.sock
```

Only the relay executable and relay socket directory belong in the Agent
sandbox or microVM.

For a microVM, the same relay also accepts a fixed numeric guest loopback port:

```text
mcp-operation-relay -loopback-port 7002
```

The Firecracker composition is deliberately indirect. The
seccomp-confined Codex domain retains no `AF_VSOCK` authority. It connects to a
guest-PID-1 loopback proxy; PID 1 opens the generation-bound host-vsock stream;
the existing peer-checked Firecracker relay fixes that stream to the same
host-owned MCP socket used by Docker. Port 7002 is now reserved in the guest
ABI. The PID 1 proxy, two VMM generations, payload relay, host socket, raw
Codex records, journal, History, and provider commits are now joined by the
real-KVM run and its offline checks.

## Exact boundary and next work

This is not yet complete mediation for an arbitrary agent. It currently:

- implements stdio, not Streamable HTTP;
- supports a deliberately bounded flat argument schema;
- depends on the supervisor to mint and correctly resume execution identity;
- protects only tools routed through this server; and
- has not yet been invoked by a real Claude client.

The Docker and Firecracker results prove containment for their exercised
Codex/MCP paths; they do not prove that every possible Agent effect path is
mediated. The Firecracker run checkpoints after the first Operation has
settled, so an MCP stream interrupted during an unknown provider write remains
unproved. A Claude runtime driver and that in-flight checkpoint case are the
next portability tests. Docker, Firecracker, QEMU, and future sandbox backends
remain replaceable containment mechanisms; the stable contract is the
host-retained Operation identity and History.

## External protocol references

- [MCP 2026-07-28 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [MCP stdio and Streamable HTTP transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [Codex MCP configuration](https://developers.openai.com/codex/mcp)
- [Codex App Server](https://developers.openai.com/codex/app-server)
- [Claude MCP integration](https://docs.anthropic.com/en/docs/mcp)
