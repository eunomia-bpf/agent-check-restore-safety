# Runtime: cross-domain system

This directory contains a runnable control layer for changing live systems
after external operations may already have happened. It crosses process,
container, network, durability, and full-VM restore boundaries.

The only five core terms are:

- **History**: the append-only, hash-linked execution record.
- **Requirement**: results that must remain achievable and resource limits that
  every possible outcome must respect.
- **Operation**: one stable external action across retries and control-state
  recovery; future adapters must preserve the same identity across restart and
  restore mechanisms.
- **Rule**: the currently enforced set of actions that cannot strand a required
  result.
- **Certificate**: history-bound evidence for activating a Rule or for reporting
  that no Rule exists in the declared model.

## Reproduce the current result

From the repository root:

```sh
make runtime-build
make runtime-test
make runtime-certcheck
make runtime-demo
make runtime-microservice-demo
make runtime-vm-demo
make runtime-codex-demo
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

## Replace a real service process

`make runtime-microservice-demo` builds and runs four separate containers:

- an order service with one process-wide release file and no old-state
  conversion code;
- the durable control service;
- an independently durable payment service; and
- a fixed ingress that exposes order and administration without opening the
  internal service network.

The order service and payment service share no Docker network. Only control
can reach payment. Both service networks are marked internal, every container
runs as the invoking host UID/GID with a read-only root filesystem, all Linux
capabilities removed, and `no-new-privileges` enabled.

The executable scenario performs these steps:

1. Start release v1 and activate a Requirement containing only `charge-v1`.
2. Submit order A-17. Payment syncs one commit, then closes the connection
   before returning a receipt, leaving its Operation `unknown`.
3. Activate a new Requirement containing only `charge-v2`, replace the entire
   order container with a release file containing only the v2 kind and target,
   and restart the control process.
4. Submit A-17 through the changed process. Its stable call identity finds the
   existing Operation in History, so control uses its frozen v1 kind and target
   while still requiring the request body to match.
5. Submit a new order B-18, which uses v2, and verify that the order container
   cannot connect directly to payment.

The checked result is three network deliveries but two durable payment
commits: two v1 deliveries for A-17 and one v2 delivery for B-18. History ends
with both Operations succeeded. Set `KEEP_DEMO=1` to leave the containers and
temporary evidence running, or `KEEP_STATE=1` to retain only the evidence
directory printed by the script.

## Keep a real Codex call alive across control replacement

`make runtime-codex-demo` is an explicit live-account experiment. It requires
an existing `codex login`, starts the official Codex App Server in an empty
temporary workspace, and does not install the deterministic model provider.
The thread is ephemeral and read-only, has sandbox network access disabled,
uses no approvals, and has MCP servers, apps, and plugins disabled. Its only
application tool accepts one fixed `effect_id`.

The real model calls that tool once. Payment durably commits and drops its
first response, so the Operation becomes `unknown`. While the App Server's
tool request is still pending, the runner terminates the control process and
starts a new one over the same History and external head anchor. The adapter
retries the same stable Operation, returns the receipt to Codex, and requires
the turn to finish with `DONE`. A final settled retry must be served from
History without contacting payment. The checked outcome is two deliveries,
one payment commit, one Codex tool call, and one callback response.

The live target is deliberately excluded from `runtime-verify`, so tests cannot
silently use account quota. Pass an explicit output path or model through, for
example:

```sh
make runtime-codex-demo \
  CODEX_DEMO_ARGS='--output-dir /tmp/codex-runtime-evidence'
```

This first live composition does not yet place Codex and payment in disjoint
network namespaces. The Docker service demo and QEMU demo enforce that network
boundary separately; combining it with the live model is the next increment.

## Check a Certificate outside the control service

`check-certificate` is a read-only binary with its own wire types, validation,
and finite-state algorithm. Its production package imports only the Go standard
library; it does not link the Rule compiler, control service, History code, or
gateway. After `/v1/compile`, post that Certificate to
`/v1/certificate-state` to obtain the versioned, compact pre-activation State
used by the checker. It contains only the facts that can change the answer, not
stored response bodies or remote metadata. Then run:

```sh
cd runtime
go run ./cmd/check-certificate \
  -state /path/to/state.json \
  -certificate /path/to/certificate.json
```

Online activation and every `rule.activated` History replay must pass this
checker before the original in-process verifier runs. Compilation itself also
runs the checker, so it cannot return a Certificate that its activation path
will reject. The compiler uses recursive search; the checker uses a separately
implemented explicit stack over the same bounded, canonical search order.

The standalone verdict is conditional on the supplied State. The binary does
not replay History, inspect the control service, or read the external head
anchor. A remote verifier must compare the verdict's History sequence and hash
with a trusted head anchor; only the online locked path derives State directly
from replayed control state.

## Restore a complete Linux VM after a remote commit

`make runtime-vm-demo` runs the stronger restore experiment on a complete,
unmodified Ubuntu 24.04 cloud image. The first run downloads the 595 MiB image
from the [official Ubuntu release directory](https://cloud-images.ubuntu.com/releases/noble/release-20260725/)
and requires the published SHA-256
`d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac`.
Later runs reuse the verified user cache. The base image remains read-only; each
run creates a temporary qcow2 overlay.

The runner uses QEMU TCG by default, so it does not require root or `/dev/kvm`:

```sh
make runtime-vm-demo
```

If the current session can open `/dev/kvm`, the same runner accepts:

```sh
make runtime-vm-demo VM_ACCEL=kvm
```

The runner creates one QEMU user network with `restrict=on`, disables all
implicit NICs, and defines only two fixed guest forwards: metadata/gate and the
Operation API. There is no forward to payment. The checked sequence is:

1. Boot Ubuntu and wait at a guest-visible gate before its Operation.
2. Stop QEMU and use `savevm` to save RAM, devices, and the qcow2 guest disk.
3. Resume the guest. Its direct connection to payment must fail. Its gateway
   request reaches payment, which syncs one commit and drops the response,
   leaving the Operation `unknown` in host History.
4. Stop QEMU, use `loadvm` to restore the complete guest to the saved point,
   and resume it. Host History and payment state are outside that restore.
5. The restored guest again fails to reach payment directly and repeats the
   identical stable call. The runtime retries the frozen Operation, obtains its
   receipt, and returns `succeeded` without a second payment commit.

The retained TCG run booted kernel `6.8.0-136-generic`, observed two remote
deliveries and one commit, and ended at host History sequence 6. The runner
also asks `qemu-img` to verify that the named internal snapshot exists. Use
`cd runtime && go run ./cmd/vm-demo -keep` to retain the guest overlay, serial
console, QEMU log, History, head anchor, and payment state for inspection.

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
  Operation progress;
- an HTTP gateway that records before network I/O, reports lost responses as
  unknown, refuses redirects away from the registered target, and retries only
  when the Operation contract says reuse is safe; HTTP status alone never
  settles an Operation;
- live-dispatch ownership that prevents two callers from concurrently sending
  the same Operation and keeps shutdown from releasing History while a request
  is live;
- a control daemon that defaults to loopback and permits a non-loopback bind
  only under an explicit flag for an isolated container network, exposing
  state, History, compilation, Rule activation, and gateway execution over a
  strict JSON API;
- adapter credentials bound to one domain and an allowed kind set, with the
  Operation identity derived server-side from that domain and call identity;
- History-based recovery of a previously registered Operation's frozen kind,
  method, and target after the calling process changes globally;
- a rootless QEMU guest path with a host-owned restricted network, a verified
  Ubuntu base image, whole-VM save/restore, and host History outside the guest
  restore domain;
- a real logged-in Codex App Server path whose dynamic-tool callback remains
  pending across control-process replacement and completes an Operation after
  a lost remote response; and
- a separately implemented, standard-library-only Certificate checker binary,
  required by both live Rule activation and durable History replay.

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

The API listens on `127.0.0.1:8787` and refuses non-loopback addresses by
default. The multi-service deployment uses the explicit non-loopback flag only
inside an internal Docker network and exposes it through a fixed loopback
ingress. On first start it creates separate private token files for
administration and adapter execution. Only the administration token can
inspect History, compile, or activate a Rule. The adapter token can create only
its configured operation kinds, and its domain is not caller supplied. A
previously created Operation remains executable under its frozen old meaning
by a credential for the same domain; this is what lets changed code finish old
work. These bearer tokens do not provide remote TLS or protection from another
process with the same host account outside the Docker deployment.

## Honest boundary

This is an early system slice, not the complete system. It does not yet provide:

- general host-level prevention of direct network or device access beyond the
  demonstrated Docker and QEMU payment boundaries;
- mediation of VM block devices, GPUs, passthrough devices, or arbitrary host
  interfaces beyond the demonstrated restricted HTTP path;
- a Claude adapter and container-enforced network isolation for the live Codex
  path;
- a replicated control service;
- authenticated remote evidence or query-based unknown-result recovery;
- a symbolic solver for large models;
- a proof-object Certificate schema that avoids full semantic recomputation;
- a compiler isolated from the privileged control-service process; or
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
