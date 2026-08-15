# Step 0009: replace a running microservice after an external commit

**Gate:** BOOTSTRAP

**Date:** 2026-08-15

**Status:** enforced multi-process slice complete; larger goal active

## Question

Can the local theorem and durable runtime seed become a system whose visible
result is qualitatively stronger than a checker or a same-process demo?

This step tests one concrete version of that claim: replace an entire business
service after a remote payment has committed but its response was lost, without
putting old-order conversion branches into the changed service.

## System added

The runnable path contains four independent Linux processes in four containers:

- `order` reads one global release file and submits a stable call identity;
- `control` owns History, the active Rule, and all payment network access;
- `payment` owns an independently synced append-only commit file; and
- `ingress` forwards only two fixed loopback entry points into otherwise
  internal Docker networks.

Order and payment share no network. Control shares one network with each, so it
is their only connection. The service networks are Docker `internal` networks.
Containers use the invoking host UID/GID, a read-only root filesystem, no Linux
capabilities, and `no-new-privileges`.

The runtime also learned to retrieve an existing Operation's frozen kind,
method, and target from History. A changed caller in the same authenticated
domain may finish that Operation, but its stable identity and request content
must still match. New work remains limited to kinds allowed by the caller's
credential and the active Rule.

## Executed change

1. Activate `orders-v1`, whose only operation kind targets `/v1/charge`.
2. Submit A-17. Payment syncs its commit and deliberately drops the response.
3. Activate `orders-v2`, whose only new kind targets `/v2/charge`.
4. Replace the entire order container with configuration containing only v2.
5. Restart the control process from its durable History.
6. Resubmit A-17 through v2 code, then submit a new B-18.
7. Attempt a direct order-to-payment connection and require it to fail.

No code in the order service selects behavior from an old per-order state. The
stable call identity is the only link supplied by the changed process.

## Observed evidence

The public command is:

```sh
make runtime-microservice-demo
```

The successful run reported:

```json
{
  "first_network_result": "unknown",
  "order_process_replaced": true,
  "changed_release": "v2",
  "control_process_restarted": true,
  "old_order_completed_under_frozen_operation": true,
  "new_order_used_v2": true,
  "direct_payment_from_order": "blocked",
  "remote_deliveries": 3,
  "remote_commits": 2,
  "delivery_paths": {
    "/v1/charge": 2,
    "/v2/charge": 1
  },
  "history_sequence": 10
}
```

The payment file contained two durable identities. Final History contained one
succeeded v1 Operation for A-17 and one succeeded v2 Operation for B-18.

## Failures that improved the boundary

The first container run failed because all capabilities were removed while the
private host state directories belonged to the invoking user. Binding every
container to that UID/GID fixed access without restoring capabilities.

The second run showed that Docker does not publish host ports from an
`internal` network. Instead of making the order network externally routed, the
system added a fixed ingress process on a separate front network. This keeps
the business and payment networks internal while permitting host-driven tests.

## Verification

- all Go packages build and test;
- the frozen old-Operation regression test passes in-process;
- payment restart, response loss, identity conflict, and one-commit behavior
  have independent unit tests;
- order propagation of an unknown result and stable call identity have unit
  tests;
- Docker Compose configuration validation passes; and
- the complete container scenario above passes, including actual failed direct
  connectivity and process replacement.

## Honest boundary and next step

This is a real enforced payment path, but not yet a production-wide egress
mechanism. The strict payment receipt is trusted through its endpoint and
isolated transport, not cryptographically authenticated. The workload is a
small application built for the experiment rather than a maintained
application. There is no replicated control service, full crash matrix,
independent Certificate checker, or VM snapshot result yet.

The next decisive system step is a complete Linux guest with a host-owned
restricted network that exposes only the Operation gateway, followed by guest
snapshot/restore after a lost remote response. A rootless TCG preflight already
showed that QEMU `restrict=on` plus one fixed guest forward can block direct host
access while permitting the gateway call; that temporary preflight is not yet
the public artifact.
