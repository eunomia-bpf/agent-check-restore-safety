# Safe change after external operations

This repository is evolving from an exact Agent-history checker into a real
runtime for changing live systems after they have interacted with the outside
world. The long-term target is one control layer for Agent runtimes, complete
Linux virtual machines, and microservices.

The current runnable slice is under [`runtime/`](runtime/). It already uses a
durable execution record, a restore-domain-external head anchor, stable external
Operation identities, state replay, history-bound Rule changes, and an HTTP
gateway with a strict receipt contract. The existing Python and Lean artifacts
remain the reference semantics and proof base; they are not presented as a
production runtime.

Run the current system evidence:

```sh
make runtime-build
make runtime-test
make runtime-demo
make runtime-microservice-demo
make runtime-vm-demo
make runtime-verify
```

The multi-service demo builds separate order, control, payment, and fixed
ingress containers. It changes and replaces the order process after a payment
has committed but its response was lost. Docker network separation prevents
the order process from reaching payment directly; the durable control path
finishes the old order and sends a new order to the new payment endpoint.

The VM demo boots a checksum-pinned Ubuntu 24.04 cloud image under QEMU, saves
the complete running guest before an Operation, then restores the guest after
the remote payment committed but its response was lost. A host-owned restricted
network exposes only metadata and control to the guest. The restored guest
repeats the call, History recovers it, and payment still commits once.

The scientific and system contract is in
[`docs/system-contract.md`](docs/system-contract.md). The current paper source
remains under [`docs/paper/`](docs/paper/) until the larger contract has enough
system and theorem evidence to justify a paper reconstruction.
