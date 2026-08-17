# Experiment plan: official Claude across complete VMM loss

Date: 2026-08-17 UTC

## Provenance

The execution contract below was frozen in the root working plan before the
final retained KVM run. Earlier development runs had already established basic
feasibility and exposed guest-permission and AF_VSOCK framing defects. This
file records the final evidence gate; it is not presented as a preregistration
before all implementation work.

## Paper-level question

RQ4 asks whether there is a deployable algorithmic boundary for safe change
after external operations. This is supporting systems evidence, not a new
result slot. It tests whether the host Operation boundary remains valid after
loss of a complete vendor-Agent VM.

## Hypothesis

A host-owned History, MCP journal, and stable Operation identity can preserve a
committed external effect across complete destruction of the Firecracker VMM
running official Claude Code. A clean replacement VM can receive the existing
result and execute the next distinct effect without duplicating the first.

## Strongest alternative explanation

Prior continuity could depend on Codex App Server callbacks, Claude process
state, a shared filesystem, or VM memory restoration. A successful cold
replacement with a new Claude session and no VM snapshot is required to reject
that explanation.

## Fixed system

- official Claude Code 2.1.233, verified through Anthropic's signed manifest;
- Firecracker 1.16.1 and Linux 6.1.155 with fixed SHA-256 digests;
- one vCPU, 1 GiB memory, no NIC, no root disk;
- a read-only SquashFS payload containing Claude, the fixed MCP relay, the
  loader, and five libraries;
- Claude runs as UID 1000;
- model and MCP connections leave the guest only through separate AF_VSOCK
  ports bound to the current VMM identity; and
- History, MCP journal, provider record, and deterministic model endpoint stay
  on the host.

## Fault and success conditions

1. The source Claude session requests A.
2. The non-idempotent provider commits A and withholds the response.
3. The supervisor kills and reaps the exact source VMM.
4. The host records A only after VMM loss.
5. A clean VM with a new Claude session requests A, receives the saved result,
   requests B, returns `DONE`, and exits successfully.

Success additionally requires two distinct VMM identities, exactly two
provider deliveries and commits, two Operations, a strict four-event failure
timeline, no network interface or root drive, and a passing checker that
imports no producer code.

## Contradictory outcomes

The hypothesis is contradicted by any duplicate A commit, dependence on a
memory snapshot, inability to finish B, shared source/replacement identity,
guest access to History or provider credentials, or a checker unable to reject
tampered evidence.

## Commands

```sh
sg kvm -c 'make runtime-firecracker-claude-demo \
  FIRECRACKER_CLAUDE_DEMO_ARGS="--evidence-dir /tmp/firecracker-claude-step-0020-final"'

make runtime-firecracker-claude-check \
  FIRECRACKER_CLAUDE_EVIDENCE=/tmp/firecracker-claude-step-0020-final
```

The final run is copied without modification into `raw/` and rechecked there.
