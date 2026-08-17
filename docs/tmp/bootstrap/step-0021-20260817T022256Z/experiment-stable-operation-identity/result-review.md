# Result Review: RQ4 stable Operation identity across Agent replacement

## Disposition

**Valid supporting result; expected answer retained.** The experiment closes a
real correctness gap in transparent Agent replacement. A recorded external
Operation can now be recovered without preserving model call identity, MCP RPC
identity, or call order. The result supports the deployability side of RQ4; it
does not by itself answer the full RQ or establish complete mediation.

## Plan and execution audit

The plan targeted the paper's restart guarantee and the canonical evaluation's
RQ4. Alternatives considered at admission were Firecracker jailer hardening,
a unified launcher, and a broader OS egress interceptor. Stable Operation
identity had higher decision value because the current real-Agent results
depended on positional replay and could mis-handle normal replacement
schedules.

The implementation was reviewed locally against the plan. No fresh independent
reviewer was used in this run because the active execution policy prohibited
delegation. Direct raw evidence, two separately implemented offline checkers,
mutation rejection, and the repository-wide regression are therefore the
decision basis; this is not represented as an independent reviewer verdict.

Three preflight issues were repaired before final execution:

1. A long evidence path exceeded the Linux Unix-socket limit. Live transport
   sockets now use a private short directory under `/tmp`; evidence remains in
   the requested directory, and cleanup is checked.
2. The Firecracker payload builder correctly refused to overwrite a payload
   whose relay input changed. The final run used a new cache directory and a
   newly bound read-only payload.
3. Firecracker cell socket names still require a short evidence root. Its final
   raw run is retained at `docs/tmp/bootstrap/s21-fc/raw/`; the longer failed
   preflight was moved to `/tmp`.

No failed preflight reached a provider commit. Final evidence was generated
fresh after the journal was additionally bound to the complete tool
configuration.

## Implemented mechanism

- Schema 2 requires each tool to select one or more already-required primitive
  arguments that identify the application's Operation. The current example
  selects `effect_id`.
- Tool name, Operation kind, and those selected arguments derive the durable
  lookup key. The full canonical request remains a separate digest; changing a
  non-identity argument under the same key is rejected before dispatch.
- Saved MCP responses use `id: null` and are rebound to the current RPC request.
- Every schema-2 journal record binds the complete normalized tool
  configuration. A restart with changed identity definitions fails closed.
- Schema-1 journals remain readable under schema 1 and cannot be silently
  reopened under schema 2.

## Direct results

### Official Codex process replacement

The source official Codex 0.147.0 App Server process committed `effect-A` after
the provider dropped its response. A second clean process requested
`effect-B` first and then `effect-A`, using distinct source and replacement
model call IDs.

- Codex processes: 2
- MCP items observed by Codex: 3 (`A`; then `B`, `A`)
- History Operations: 2
- Provider deliveries: 2
- Provider commits: 2
- Source A and replacement B journal RPC IDs: both `2`
- Replayed A provider dispatches: 0
- Journal records: 4, with two prepared/completed Operations
- Offline checker: pass
- Relocated unmodified copy: pass
- Relocated copy with changed `config_digest`: reject

The crucial observation is not merely successful replay. The two distinct new
Operations arrived with the same RPC ID in different Agent lifetimes, while A
was later reused from a different call position. Positional schema 1 cannot use
that RPC ID as both A and B; schema 2 records both correctly.

Raw evidence:
`docs/tmp/bootstrap/step-0021-20260817T022256Z/experiment-stable-operation-identity/raw/`.

### Official Claude across complete Firecracker loss

Official Claude Code 2.1.233 ran as UID 1000 in two Firecracker 1.16.1
microVMs with Linux 6.1.155, no NIC, no root disk, and a read-only SquashFS
payload containing the current relay.

- Source VMM PID: `2822739`
- Replacement VMM PID: `2822797`
- Source disposition: pidfd-bound VMM `SIGKILL` and reap after provider commit A
- Replacement result: `DONE`
- History Operations: 2
- Provider deliveries and commits: 2 and 2
- Journal schema: 2, bound to the tool configuration
- Offline Firecracker/History/journal checker: pass

Raw evidence: `docs/tmp/bootstrap/s21-fc/raw/`.

## Controls and regressions

Go tests cover legacy schema-1 replay, schema mismatch, configuration mismatch,
changed full requests under one Operation identity, changed RPC IDs, reordered
replacement relays, response rebinding, journal reopen, pending calls, and
durable fences. The real provider-independent MCP boundary test passes.

`make runtime-verify` passed on 2026-08-17. It included all Go builds, all Go
race tests, `go vet`, 114 Python tests, and retained Codex isolation, integrated
KVM, and DeathStar microservice evidence checks. One earlier unconstrained Go
run observed the known timing-sensitive Firecracker close test fail once; its
immediate isolated rerun and the final race-enabled full suite passed.

## Interpretation

The expected answer is supported: an application field already needed by the
tool can preserve Operation identity across Agent replacement without changing
Claude or Codex. Firecracker adds containment and failure control but is not the
continuity mechanism; the host History and Operation journal survive outside
the VM.

The strongest competing explanation—that Agent-native call IDs are stable
enough—does not fit the Codex evidence. Different work reused MCP RPC ID `2`
across processes, and the same A appeared later under a different model call
identity and call position.

## Limits and next decision

This experiment uses a deterministic local model endpoint and one functional
run per real Agent path. It does not measure latency, infer identity from text,
mediate arbitrary built-in tools or raw network traffic, run Firecracker
`jailer`, or establish fleet availability. The operator must expose a stable
required application field. A full real schema-1 baseline was not executed;
its behavior is covered by compatibility tests and follows directly from its
RPC-ID-indexed journal, but no comparative performance or completion rate is
claimed.

The next higher-value step is not another VM demo. It is a transparent launcher
and policy package that makes this host boundary the default for Claude/Codex
and service processes, followed by one maintained application with enforced
egress. That will test adoption cost and bypass resistance rather than another
instance of the already demonstrated crash path.
