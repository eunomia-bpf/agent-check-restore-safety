# Claude continuity across complete Firecracker loss

This target runs the pinned official Claude Code 2.1.233 executable as an
unprivileged user inside a real Firecracker microVM. The VM has no network
interface and no root block device. Its only software drive is a read-only
SquashFS image containing Claude, a fixed MCP byte relay, the dynamic loader,
and five libraries.

This is not a new sandbox API. Firecracker supplies replaceable containment;
the host runtime preserves the facts that must outlive it. Claude uses an
ordinary explicit MCP configuration and needs no restore-specific plugin.

## Boundary

Inside each VM:

- official Claude Code runs as UID 1000;
- one fixed relay carries MCP bytes over AF_VSOCK;
- the model connection also crosses a separate AF_VSOCK port; and
- a small PID 1 verifies the payload hashes and returns the final Claude
  stream through a one-result gate.

Outside every VM:

- History and its external head remain on the host;
- the MCP process owns the durable call journal and Operation identity;
- the provider owns its independently durable commit record; and
- a deterministic local Anthropic-protocol endpoint supplies model responses
  without giving the VM a network device.

The model endpoint is a protocol fixture. The official Claude executable,
MCP client, process lifecycle, Firecracker/KVM isolation, and external
Operation path are the systems under test.

## Failure experiment

Claude first requests `effect-A`. The provider commits A and deliberately
holds its response. The supervisor then sends `SIGKILL` through the exact
pidfd-bound Firecracker process and reaps the VMM. Only after that loss does
the host finish recording A.

The runtime boots a clean second VM; it does not restore a memory snapshot.
The second Claude session requests A, receives the saved MCP result without a
second provider delivery, requests `effect-B`, and returns `DONE`. A successful
run therefore has two different VMM identities, two Operations, two provider
deliveries, and exactly two provider commits.

The current tool configuration derives Operation identity from the required
`effect_id` argument, not from Claude's RPC ID or call position. Saved journal
responses contain no RPC ID and are rebound to the replacement request. The
journal is also bound to the exact tool configuration, so an identity-definition
change cannot silently reinterpret an existing execution.

## Reproduce

The target requires Linux x86-64, `mksquashfs`, and read/write access to
`/dev/kvm`. It downloads pinned Firecracker and kernel assets and verifies the
signed Claude release manifest.

```sh
sg kvm -c 'make runtime-firecracker-claude-demo \
  FIRECRACKER_CLAUDE_DEMO_ARGS="--evidence-dir /tmp/firecracker-claude-run"'
```

Check the retained run with code that imports none of the producer:

```sh
make runtime-firecracker-claude-check \
  FIRECRACKER_CLAUDE_EVIDENCE=/tmp/firecracker-claude-run
```

The checker recomputes artifact hashes, parses the binary History, joins the
MCP journal to provider commits, verifies the strict failure ordering, checks
the official Claude stream, and confirms that both AF_VSOCK paths were bound
to the corresponding VMM process. It also checks that Firecracker configured
no NIC or root drive and mounted only the declared read-only payload. The
latest schema-2 run is retained under `docs/tmp/bootstrap/s21-fc/raw/`.

## Current limit

This is one functional KVM result, not a performance or fleet-management
claim. The runner does not yet use Firecracker `jailer`, remote attestation,
or a dedicated host identity. This target covers declared MCP Operations. A
separate target now covers one registered built-in Bash/HTTP action against
unmodified DeathStarBench across complete VMM loss; see
`docs/firecracker-deathstar-runtime.md`. Arbitrary tools and protocols remain
open. The next production step is to place the host boundary behind a normal
agent-runtime launcher so process, container, and VM isolation become
deployment choices rather than separate integrations.
