# Runtime: first vertical slice

This directory contains the first runnable slice of a control layer for
changing live systems after external operations may already have happened. It
is deliberately small, but it crosses a real network and durability boundary;
it is not an architecture placeholder.

The only five core terms are:

- **History**: the append-only, hash-linked execution record.
- **Requirement**: results that must remain achievable and resource limits that
  every possible outcome must respect.
- **Operation**: one stable external action across retries and control-state
  recovery; future adapters must preserve the same identity across their own
  branch, restart, and restore mechanisms.
- **Rule**: the currently enforced set of actions that cannot strand a required
  result.
- **Certificate**: history-bound evidence for activating a Rule or for reporting
  that no Rule exists in the declared model.

## Reproduce the current result

From the repository root:

```sh
make runtime-build
make runtime-test
make runtime-demo
make runtime-verify
```

The demo starts a separate HTTP payment endpoint in the same demo process,
backed by its own synced file. The endpoint commits a charge and deliberately
drops the first response. The durable control object is closed and reopened,
retries with the same Operation identity, and recovers a validated receipt. The
endpoint sees two deliveries but one durable commit. This demo does not claim a
process-kill or separate-machine experiment.
The same run also shows that:

- an individually valid action is blocked when it would consume the only
  resource needed by a still-required payment;
- a Certificate becomes stale after any Operation progress, even when a view
  containing only authorization events would be unchanged; and
- a settled retry returns the recorded result without another network call.

## Implemented now

- a single-writer, length-framed History with SHA-256 chaining, `fsync`, strict
  replay, corruption rejection, safe repair of an incomplete final write, and
  permanent fail-closed state after an unsuccessful repair;
- an external History-head anchor that detects restoration of an older valid
  History when the anchor is placed outside the restored storage domain;
- stable Operation identity and frozen costs/results across rule changes;
- durable `prepared`, `dispatched`, `unknown`, `succeeded`, `failed`, and
  `cancelled` phases;
- bounded analysis of every possible outcome of up to 12 open Operations,
  exact within the currently implemented stable-retry subclass, with explicit
  model and search budgets reported as resource errors rather than refusals;
- an exact finite planner that checks whether all required results still fit
  within remaining resources;
- Rule activation tied to the complete History head and serialized with all
  Operation progress; and
- an HTTP gateway that records before network I/O, reports lost responses as
  unknown, refuses redirects away from the registered target, and retries only
  when the Operation contract says reuse is safe; HTTP status alone never
  settles an Operation;
- live-dispatch ownership that prevents two callers from concurrently sending
  the same Operation and keeps shutdown from releasing History while a request
  is live;
- a loopback-only control daemon exposing state, History, compilation, Rule
  activation, and gateway execution over a strict JSON API; and
- adapter credentials bound to one domain and an allowed kind set, with the
  Operation identity derived server-side from that domain and call identity.

Run the daemon directly:

```sh
cd runtime
mkdir -p /tmp/running-change-host
go run ./cmd/control \
  -history /tmp/running-change.history \
  -head-anchor /tmp/running-change-host/running-change.head \
  -operation-domain example-service \
  -operation-kinds charge-invoice
```

The anchor directory must already exist. For VM restore protection, the anchor
must be on the host or a remote monotonic store, not inside the guest image.
The adjacent default anchor catches isolated History replacement but not a
snapshot that rolls back both files.

The API listens on `127.0.0.1:8787` and refuses non-loopback addresses. On first
start it creates separate private token files for administration and adapter
execution. Only the administration token can inspect History, compile, or
activate a Rule. The adapter token can call only its configured operation
kinds, and its domain is not caller supplied. These tokens do not prevent
another process running as the same Unix user from bypassing the gateway, so
this API is not yet the host enforcement boundary.

## Honest boundary

This is milestone zero, not the complete system. It does not yet provide:

- host-level prevention of direct network or device access;
- a QEMU/KVM guest adapter or a real VM snapshot experiment;
- Codex and Claude adapters to this new control layer;
- a replicated control service;
- authenticated remote evidence or query-based unknown-result recovery;
- a symbolic solver for large models;
- a separately implemented Certificate checker; or
- an end-to-end proof that concrete Agent, VM, and service executions refine the
  finite model.

The bounded planner is useful executable evidence, not a novelty claim about
maximally permissive control. It currently refuses kinds whose lost response
cannot be recovered by the implemented gateway; the `Queryable` field is
reserved for the next adapter and is not treated as working evidence. The
current HTTP adapter accepts only a registered, strictly decoded receipt that
binds a settled outcome to the Operation identity. A 202, 5xx, redirect, or
unrecognized 2xx body remains unknown. The receipt is a fixed durable schema,
so arbitrary service response bodies are not copied into History. The endpoint
and transport are still trusted; authenticated query evidence is not yet
implemented. The planned contribution is the derivation of the model from real
execution records and its enforced correspondence to concrete systems.
