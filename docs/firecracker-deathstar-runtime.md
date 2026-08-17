# Ordinary Claude HTTP across Firecracker loss and DeathStarBench

This target runs official Claude Code 2.1.233 in networkless Firecracker
microVMs and lets Claude use its built-in Bash tool to send an ordinary HTTP
reservation. The receiver is the complete unmodified DeathStarBench Hotel
Reservation 0.3.5 application. After the application commits the reservation
but before any response byte reaches Claude, the supervisor kills the complete
source VMM and starts a clean replacement.

Firecracker is a replaceable isolation and failure backend. The host runtime,
not VM memory, preserves the external action across replacement.

## Boundary

Each microVM contains:

- the pinned official Claude executable;
- real Bash, BusyBox, the dynamic loader, and fixed libraries;
- no NIC and no root block device;
- one read-only SquashFS payload; and
- fixed AF_VSOCK relays for the model and the registered HTTP route.

The host contains:

- durable History and Operation state;
- an exact `/v1/reserve` route registered by the operator;
- a generation-bound Unix socket for that route;
- the full 24-service DeathStarBench graph; and
- a read-only Mongo observer that retains the facts used for recovery.

Claude, its prompt, and DeathStarBench are unchanged. The operator registers
the route and its query method. The guest receives only a fixed local URL and a
call identity; it receives no application credential or general network
access.

## Failure and comparison

The protected condition sends the request through the host route. Once
DeathStarBench has committed and the Mongo observer has found the row, the
source VMM is killed while its relay still records zero response bytes. The
runtime moves the Operation to unknown, binds a new generation, queries the
application facts, and returns the existing result to a clean replacement VM.
An explicit call through the old generation must fail before reaching the
application.

The same Claude command and failure point run under two comparisons:

- raw retry starts a replacement without History and creates a second Mongo
  row; and
- stop after loss avoids a duplicate but cannot complete the Agent task.

The accepted three-run result is protected `[1,1,1]`, raw `[2,2,2]`, and stop
`1` without task completion. All 19 Mongo queries and their matching rows are
retained before the database volume is removed.

## Reproduce

Requirements are Linux x86-64, Docker Compose, `mksquashfs`, BusyBox, and
read/write access to `/dev/kvm`. The launcher fetches checksum-pinned
Firecracker and kernel artifacts, verifies Anthropic's signed Claude release,
clones the exact DeathStarBench commit, builds the runtime, and retains the
complete evidence directory.

```sh
sg kvm -c 'make runtime-firecracker-deathstar-demo'
```

Check the retained result with code that imports no experiment producer:

```sh
make runtime-firecracker-deathstar-check
```

Override `FIRECRACKER_DEATHSTAR_EVIDENCE` to retain a different directory and
`FIRECRACKER_DEATHSTAR_REPETITIONS` to change the repetition count. The default
checker requires three repetitions.

The checker independently:

- parses and rehashes binary History;
- recomputes Operation and HTTP request identities;
- reconstructs every expected Mongo business row and fact hash;
- joins application commit, Mongo observation, VMM stop, and relay-byte order;
- checks generation fencing and exact delivery counts;
- verifies Firecracker devices, processes, and immutable payloads; and
- parses the official Claude stream to require one built-in Bash call and
  successful completion only in replacement cells.

## Current limit

This target is a functional correctness result, not a performance or
production-readiness result. It covers one operator-registered plaintext HTTP
route, a fixed queryable request, and a deterministic model endpoint. It does
not transparently handle arbitrary HTTPS, raw sockets, unqueryable actions,
remote attestation, device output, or fleet scheduling. Raw retry is a matched
lower bound; the result does not claim superiority over receiver-side
idempotency.
