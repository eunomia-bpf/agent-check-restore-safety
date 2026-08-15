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

## Protect an existing HTTP effect

The reusable path requires no workflow-engine plugin. Build the two operator
tools:

```sh
cd runtime
go install ./cmd/safe-change ./cmd/effect-proxy
```

Declare the result that must remain achievable and the fixed HTTP operation
that can produce it:

```json
{
  "id": "orders-v1",
  "results": {"paid": 1},
  "capacities": {"charge": 1},
  "kinds": {
    "charge": {
      "costs": {"charge": 1},
      "produces": {"paid": 1},
      "retry_safe": true,
      "queryable": false,
      "target": "http://payment.internal/v1/charge",
      "method": "POST",
      "response_classifier": "operation-receipt-v1"
    }
  }
}
```

With `control` already running, plan and apply the change. `plan` obtains a
Certificate and checks it with the independent implementation before writing
it. `apply` checks it again against the current History, so a stale or
`impossible` decision never reaches activation.

```sh
safe-change plan \
  -control http://127.0.0.1:8787 \
  -admin-token-file /run/safe-change/admin-token \
  -requirement requirement.json \
  -out certificate.json

safe-change apply \
  -control http://127.0.0.1:8787 \
  -admin-token-file /run/safe-change/admin-token \
  -certificate certificate.json
```

Do not give the workload the adapter token or the payment address. Put both in
an operator-owned route file and run the proxy beside the workload:

```json
{
  "schema": 1,
  "routes": [{
    "name": "payment",
    "kind": "charge",
    "method": "POST",
    "url": "http://payment.internal/v1/charge",
    "content_types": ["application/json"]
  }]
}
```

```sh
effect-proxy \
  -listen 127.0.0.1:8788 \
  -control-url http://127.0.0.1:8787 \
  -adapter-token-file /run/safe-change/adapter-token \
  -config routes.json
```

Application code now sends only a stable logical call ID and its business
payload:

```sh
curl -X POST http://127.0.0.1:8788/v1/effects/payment \
  -H 'X-Safe-Change-Call-ID: order/A-17/payment' \
  -H 'Content-Type: application/json' \
  --data '{"order_id":"A-17","amount":42}'
```

The call ID must identify the same business action across retries and must not
contain an attempt number. The proxy makes one control call, never accepts a
caller-selected target, forwards no caller credentials, and returns `409` when
an external outcome is not safely settled. In a container deployment, place
the workload, proxy, control, and effect on successive isolated networks so
each process can reach only its next hop.

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
make runtime-codex-isolated-demo
make runtime-codex-isolated-check
make runtime-integrated-demo
make runtime-integrated-check
make runtime-deathstar-demo
make runtime-deathstar-check
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
network namespaces. Use the stronger target below for an enforced composition.

### Enforce the boundary around the real model

`make runtime-codex-isolated-demo` builds the control/payment image and runs the
logged-in Codex App Server in a separate hardened container. Its root filesystem
and workspace are read-only, Linux capabilities are removed, and only a private
temporary copy of `auth.json` is mounted read-write. Codex has the agent network
needed for its model connection; payment has only an internal effects network;
control is the sole bridge. Before any payment, the runner first requires a
control-health request from inside Codex to succeed, then checks both the
payment DNS name and its actual effects-network IP and requires both to fail.
After the model emits its tool call, the temporary account copy is deleted
before control may contact payment. Codex completes the pending turn without
that file, and the original account file is never mounted or modified.

The model's callback stays pending while payment commits, its first response is
lost, and the complete control container restarts over the same History. The
second delivery returns the one durable receipt, the settled retry reuses that
receipt, and Codex replies exactly `DONE`. Before Rule activation, the separate
Certificate checker validates the exported state. After shutdown, another
checker independently replays the binary History chain and cross-checks the
external head, payment file, privacy-filtered App Server JSONL, final state, and
minimal saved Docker container and network projections. The retained protocol
contains one dynamic-tool item and no built-in-tool item; this is an observation
about that turn, not a claim that the executable has no other capabilities. The
retained run is checked without using account quota:

```sh
make runtime-codex-isolated-check
```

The live target remains deliberately excluded from `runtime-verify`; its saved
evidence checker is included. A new live run accepts, for example:

```sh
make runtime-codex-isolated-demo \
  CODEX_ISOLATED_DEMO_ARGS='--output-dir /tmp/codex-isolated-evidence'
```

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

## Run one purchase across Codex, a service, and a full VM

`make runtime-integrated-demo` is the first vertical system target. It requires
an existing `codex login` and combines, in one purchase and one History:

- a real logged-in Codex App Server in a hardened container;
- a replaceable order microservice;
- a complete Ubuntu 24.04 QEMU guest restored from a live `savevm` snapshot;
- one durable control service; and
- separate payment, inventory, and ledger services with separate synced files.

Codex calls `complete_purchase` once and waits for one callback that covers all
three Operations. Its payment Operation and the order service's inventory
Operation each commit remotely and lose their first response. The VM's ledger
Operation succeeds before the Rule change. Against History head sequence 10,
the runner compiles Rule v2, whose order kind is `reserve-v2`, and records its
activation at sequence 11. It then replaces the order container and restarts
the control process. The new order process requests the v2 kind and
`/v2/charge`, but its stable call identity recovers the earlier Operation, so
control preserves the frozen `reserve-v1` kind and `/v1/charge` target. No
request reaches the inventory v2 path.

The runner next loads the complete VM snapshot. The guest repeats the same
audit call, receives the result already recorded in History, and reports
`reused=true`; ledger receives no second delivery. The replacement control
recovers the unknown payment and inventory Operations, settled retries reuse
both results, and Codex receives the three results and replies exactly `DONE`.
History ends at sequence 15 with all three Operations succeeded. The observed
external totals are:

| Service | Deliveries | Durable commits | Observed path |
|---|---:|---:|---|
| payment | 2 | 1 | `/v1/charge` |
| inventory | 2 | 1 | `/v1/charge` |
| ledger | 1 | 1 | `/v1/charge` |

Docker provides three network domains. Codex joins only the agent network;
order joins only the internal application network; payment, inventory, and
ledger join only the internal effects network. Fixed ingress and control form
the only cross-network path. Saved probes show that Codex and order can reach
their intended next hop but cannot reach any effect service by either name or
address. QEMU has no implicit NIC and uses one `restrict=on` user network with
only metadata and shared-control guest forwards; the guest's direct effect
probe fails both before and after restore.

The retained run used TCG. It is evidence that the composition and whole-VM
save/load path execute, not a latency, throughput, or KVM claim. The order and
effect services are purpose-built test services, not a maintained application.
Run a fresh live experiment with, for example:

```sh
make runtime-integrated-demo VM_ACCEL=tcg \
  INTEGRATED_DEMO_ARGS='--output-dir /tmp/integrated-runtime-evidence'
```

The retained evidence and its current verification status are documented in
[`step-report.md`](../docs/tmp/bootstrap/step-0014-20260815T133621Z/step-report.md).
The live target is excluded from `runtime-verify` so ordinary tests cannot use
account quota. The retained run is checked without account access:

```sh
make runtime-integrated-check
```

That checker does not import the live runner. It replays the binary History,
reruns both Certificate checks, and joins the effect, Docker, App Server, and
QEMU records. Mutation tests require it to reject changed History bytes, QMP
restore commands, network membership, Codex tool identity, and inventory paths.

## Delete an old real-service version after its effect commits

`make runtime-deathstar-demo` runs against two pinned, source-clean releases of
the unmodified DeathStarBench Hotel Reservation application. It starts the
complete 24-service v2 Compose definition with its official frontend scaled to
zero, then supplies separately built v1 and v2 frontends. Project code provides
only the protected effect endpoint and a read-only Mongo observer.

The deterministic fault occurs after the official application has inserted a
reservation document but before the protected endpoint returns any HTTP bytes.
Three matched conditions show the boundary:

| Condition | Deliveries | Mongo rows | Available | Keeps v1 |
|---|---:|---:|---|---|
| raw retry | 2 | 2 | yes, but duplicates | yes |
| old-version drain | 1 | 1 | no | yes |
| History query recovery | 2 total across old and new work | 2 | yes | no |

In the runtime condition, the old Operation is delivered exactly once. The
runner activates Rule v2, removes both the v1 frontend and v1 effect process,
starts their v2 replacements, and restarts control over the same History. The
replacement runtime asks the frozen observer contract about the old Operation;
one exact Mongo document settles it without another effect delivery. A new v2
Operation then commits through the v2 frontend. Four Docker networks enforce
that effect cannot reach Mongo, observer cannot reach the application path, and
control cannot reach application state directly.

The retained run ends at History sequence 9 and is independently checked with:

```sh
make runtime-deathstar-check
```

The checker replays the binary History, reruns both Certificate checks, and
joins raw Mongo documents, five observations, two upstream Git trees, the
24-service graph, old-container removal, and eight network probes. All 12
evidence mutations are rejected. Full provenance and limitations are in
[`step-report.md`](../docs/tmp/bootstrap/step-0015-20260815T141250Z/step-report.md).

This is a deliberately narrow positive result: one hotel, one night, one room,
and a unique customer derived from the Operation identity. Exactly one matching
document proves success; zero or multiple matches remain inconclusive. The
observer is a local trusted component, and recovery still requires the caller
to resupply request bytes matching the hash in History. This is neither a
general exactly-once claim nor proof that every unknown Operation can finish.

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
  exact relative to declared stable-retry and query capabilities, with explicit
  model and search budgets reported as resource errors rather than refusals;
- an exact finite planner that checks whether all required results still fit
  within remaining resources;
- Rule activation tied to the complete History head and serialized with all
  Operation progress;
- an HTTP gateway that records before network I/O, reports lost responses as
  unknown, refuses redirects away from the registered target, queries the
  frozen observer contract before any retry, and retries only when the
  Operation contract says reuse is safe; HTTP status alone never settles an
  Operation;
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
- a real logged-in Codex App Server path whose hardened container cannot reach
  any of three effect services by network name or IP, and one integrated run in
  which the pending callback spans an order-container replacement, a control
  restart, a Rule change, and a complete QEMU VM restore;
- an unmodified DeathStarBench application path where a Mongo commit with a
  lost response is recovered after deleting v1, without redispatch, and a v2
  Operation then completes through the replacement frontend; and
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

- a maintained production application workload; DeathStarBench is a real,
  unmodified benchmark but not the eventual maintained order/payment target;
- general host-level prevention of direct network or device access beyond the
  demonstrated Docker and QEMU HTTP boundaries;
- mediation of VM block devices, GPUs, passthrough devices, or arbitrary host
  interfaces beyond the demonstrated restricted HTTP path;
- a live Claude adapter and a provider-independent Agent protocol;
- a replicated control service;
- signed or remotely attested observation evidence and complete negative
  observations; the current Mongo observer is local and trusted;
- repeated KVM runs, scale measurements, and comparisons with the declared
  system baselines;
- a symbolic solver for large models;
- a proof-object Certificate schema that avoids full semantic recomputation;
- a compiler isolated from the privileged control-service process; or
- an end-to-end proof that concrete Agent, VM, and service executions refine the
  finite model.

The bounded planner is useful executable evidence, not a novelty claim about
maximally permissive control. It refuses kinds whose lost response has neither
stable retry nor a registered query contract. `Queryable` is a strong model
assumption: an implementation must eventually produce a definitive observation
for the liveness reasoning to apply. The DeathStarBench observer establishes
only the positive one-document case and fails closed on zero or multiple rows,
so the retained run proves the fixed commit-then-loss History rather than that
assumption for every fault timing. Receipts and observations are strictly
decoded and bound to the Operation identity and request hash; an unrecognized
response remains unknown. The endpoint, transport, and local observer are still
trusted, and authenticated remote evidence is not yet implemented. The planned
contribution is the derivation of the model from real execution records and its
enforced correspondence to concrete systems.
