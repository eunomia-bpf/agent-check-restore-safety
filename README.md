# Safe change after external operations

Change a live service without letting an interrupted external operation run
twice or silently move to the new destination. Try the current end-to-end
prototype with one command:

```sh
make safe-change-demo
```

The demo starts an order service whose payment commits while its response is
lost, activates a new release, replaces the order service and effect proxy, and
restarts the control service. Retrying the interrupted order completes against
its original payment operation; a new order uses the new release. The order
service submits only a stable call ID, the logical `payment` route, and its
payload. It holds neither an operation token nor a physical payment target.

To put the runtime beside your own HTTP service, build the minimal image with
`make runtime-image` and use the copyable
[`runtime/deploy/starter/`](runtime/deploy/starter/) Compose skeleton. It keeps
workload, control, and provider access on separate networks and includes
checked examples for activating and changing a provider adapter.

This repository is evolving from an exact Agent-history checker into a common
control layer for changing Agent runtimes, complete Linux virtual machines, and
microservices after they have interacted with the outside world. It is a
runnable research prototype, not a production-ready system.

The current runnable slice is under [`runtime/`](runtime/). It already uses a
durable execution record, a restore-domain-external head anchor, stable external
Operation identities, state replay, history-bound Rule changes, and an HTTP
gateway with a strict receipt contract. The existing Python and Lean artifacts
remain the reference semantics and proof base; they are not presented as a
production runtime.

Run the broader system and research evidence:

```sh
make runtime-build
make runtime-test
make runtime-certcheck
make runtime-image
make runtime-starter-check
make runtime-demo
make runtime-microservice-demo
make runtime-vm-demo
make runtime-vm-check VM_EVIDENCE=/tmp/safe-change-vm-123456789
make runtime-firecracker-kvm-test
make runtime-mcp-operation-check
make runtime-codex-mcp-demo
make runtime-codex-mcp-docker-demo
make runtime-firecracker-codex-mcp-demo
make runtime-firecracker-codex-mcp-inflight-demo
make runtime-codex-demo
make runtime-codex-isolated-demo
make runtime-codex-isolated-check
make runtime-integrated-demo
make runtime-integrated-check
make runtime-deathstar-demo
make runtime-deathstar-check
make runtime-verify
```

The multi-service demo runs order, effect-proxy, control, and payment containers,
separate order and control ingress containers, and short-lived `safe-change`
CLI jobs. It changes and replaces the order process after a payment has
committed but its response was lost. Docker network separation prevents both
order and effect-proxy from reaching payment directly; the durable control path
finishes the old order and sends a new order to the new payment endpoint.

The VM demo boots a checksum-pinned Ubuntu 24.04 cloud image under QEMU, saves
the complete running guest before an Operation, then restores the guest after
the remote payment committed but its response was lost. A host-owned restricted
network exposes only metadata and a VM-specific, credential-free Operation
endpoint to the guest. While the restored VM remains paused, the host replaces
its Rule and VM binding before reconnecting and resuming it. The restored guest
repeats the call, History recovers it, and payment still commits once.

The optional Firecracker backend runs the same restore boundary with two real
microVM processes, a static initramfs guest, no NIC, no root disk, and one
generation-bound vsock relay per active microVM. Its real-KVM test and
independent evidence checker are available with
`make runtime-firecracker-kvm-test`; the integrated Agent runtime selects it
with `VM_BACKEND=firecracker VM_ACCEL=kvm`. This path is currently an unjailed
functional prototype, not yet a production sandbox.

A second, credential-free Firecracker path runs the exact native Codex App
Server inside the microVM while preserving its ordinary stdin/stdout boundary.
It holds one dynamic-tool callback, snapshots and kills the first VMM, loads
the whole guest into a different paused VMM, reconnects the retained stream,
and only then releases the callback. Build, real-KVM, checker, trust-boundary,
and current limitation details are in
[`docs/firecracker-codex-runtime.md`](docs/firecracker-codex-runtime.md).

That Firecracker path now also supports the ordinary Codex MCP boundary. The
MCP host and fsynced journal stay outside the VM; the guest contains only a
fixed relay reached through PID 1. A checked KVM run completed A, replaced the
whole VMM from snapshot, replayed A without another provider write, and then
committed B. `make runtime-firecracker-codex-mcp-check` independently verifies
both the VM lifecycle and the Codex-to-journal-to-History-to-provider join.

The stronger in-flight target snapshots while A is already durable at the
provider but still unresolved in Codex. The host classifies a snapshot with
active external I/O as nonportable, completes the capture without loading it
into another VMM, and starts a fresh microVM. The new Codex session obtains A
from the host journal before it submits B. Thus Firecracker supplies
replaceable containment; it is not the source of external-operation
correctness.

The Codex demo uses the locally logged-in account and the real Codex App Server,
not a model fixture. A strict dynamic tool requests one application-chosen
Operation. Payment commits and loses its first response; while the tool callback
is pending, the control process is replaced. The restarted control process
finishes the same Operation, Codex replies `DONE`, and payment retains one
durable commit. This explicit live-account target is not run by ordinary tests.

The credential-free MCP targets exercise a different production boundary with
no account requirement. Two real Codex App Server instances each launch a tiny
untrusted stdio relay, while one trusted host process retains call identity and
the fsynced journal across both relay lifetimes. The stronger target replaces
two hardened Docker containers on a private internal network. Their only
continuity mounts are a read-only relay bundle and host-socket directory; raw
Docker inspection and direct-provider probes are checked offline. The first
payment commits and loses its response; the host recovers it by query, returns
the exact result after Codex restarts, and then admits a distinct payment. The
checker also proves from raw Codex commands that the Agent receives no journal,
execution identity, sandbox binding, provider route, or credential. The same
contract now runs inside Firecracker without changing the MCP tool surface.
See
[`docs/mcp-continuity-runtime.md`](docs/mcp-continuity-runtime.md).

The stronger isolated target runs that same real App Server inside a hardened
Docker boundary. Codex and payment share no network; control is the only
container attached to both networks. After a positive control-health probe, the
retained run proves that both DNS and direct-IP probes from Codex to payment
fail, while the protected Operation
survives control-process replacement. A separate checker replays the binary
History and joins it with the external head, payment record, and raw App Server
protocol without importing the live runner.

The integrated target is the first single execution across all three runtime
frontends. A real logged-in Codex App Server, a replaceable order service, and
a complete Ubuntu QEMU guest issue three Operations into one shared History
and three separately durable effect services: payment, inventory, and ledger.
The VM has no adapter token and cannot select its domain, provider target, HTTP
method, or provider headers. QEMU forwards its three-field request to a private
Unix socket owned by control. The run advances that host binding through three
generations, replaces the order container, restarts control, proves that replay
does not reattach the old endpoint, and only then restores the whole VM from a
live snapshot. Codex and order have no direct network path to any effect
service. The retained KVM run observed five deliveries but only three commits:
two deliveries each to payment and inventory and one to ledger. The v2 order
process recovered the old Operation's frozen `reserve-v1` target; the restored
VM reused its recorded audit result without another ledger delivery. This is a
functional cross-domain result, not a performance result or a
maintained-application evaluation. Its evidence and remaining limits are in
[`step-report.md`](docs/tmp/bootstrap/step-0018-20260816T125801Z/step-report.md).
The account-free `make runtime-integrated-check` command independently replays
the retained History and joins it with the effect, Docker, App Server, and QEMU
records.

The first unmodified application result uses two pinned DeathStarBench Hotel
Reservation releases. After v1 commits a real Mongo reservation and its reply
is lost, the runtime deletes the v1 frontend and effect process, restarts over
the same History, settles the old Operation from one exact database fact, and
then completes new work through v2. A raw retry produces two database rows;
keeping v1 avoids duplication only by staying unavailable. The independent
`make runtime-deathstar-check` path replays History and joins the raw Mongo,
upstream source, container-removal, and four-network evidence without starting
Docker.

The scientific and system contract is in
[`docs/system-contract.md`](docs/system-contract.md). The current paper source
remains under [`docs/paper/`](docs/paper/) until the larger contract has enough
system and theorem evidence to justify a paper reconstruction.
