# Firecracker Codex continuity runtime

**Status:** working real-KVM vertical prototype, 2026-08-16. One real Codex
callback, VM replacement, external commit, and repository Cutover now share a
single durable History. It is not yet a production sandbox or general agent
runtime.

## What the system is

An ordinary Codex App Server client is given a temporary `codex` executable.
The client does not know that this executable starts a Firecracker runtime.
Inside the microVM, the exact native Codex binary runs against a read-only
payload and a workspace materialized from a canonical read-only repository
drive. The guest has no NIC and receives no account credential. A host-owned
model relay is the only model path.

At one declared dynamic-tool boundary, the runtime:

1. retains the callback instead of exposing it to the client;
2. establishes a two-way stream checkpoint and drains the model path;
3. pauses the first VM, creates a full snapshot, sends `SIGKILL` to the exact
   first VMM, and waits for that child to be reaped;
4. starts a different VMM, loads the sealed snapshot while paused, installs
   authenticated host endpoints, resumes it, and reconnects the retained
   stream; and
5. exposes the callback only after the restored guest is attached. The host
   sends it through a credential-free Unix socket owned by that exact sandbox
   generation; the guest cannot choose its identity, provider URL, method, or
   provider headers. Success is
   reported only after the matching callback result has entered the retained
   stream, the same Codex turn has completed successfully, that completion has
   reached the client, and client input has closed; and
6. sends an authenticated shutdown to the guest, freezes and empties the
   complete Codex cgroup, exports the resulting full repository tree, and
   derives the canonical delta on the host.

Firecracker supplies isolation and whole-machine snapshot/restore. It is a
replaceable mechanism, not the research claim. The runtime contribution is the
continuity boundary around it: external progress that a snapshot cannot erase
is joined with the History/Rule control plane and the repository state that a
replacement VM receives. This slice now performs that vertical join for one
real Codex callback.

## Components

- `adapter/firecracker_codex.py` creates the transparent executable and fixes
  all host-owned inputs. It supervises the runner and bounds raw diagnostics.
- `runtime/cmd/firecracker-codex-shim` owns both VMM processes, snapshot files,
  relays, state transitions, and retained evidence.
- `runtime/cmd/firecracker-agent-guest` is the guest PID 1. It mounts the
  read-only payload, verifies and materializes the repository drive, creates an
  isolated non-root child directly in a cgroup-v2 execution domain, installs a
  fail-closed syscall filter, reaps orphans, freezes and kills every descendant
  at completion, and carries the Codex stream and final tree over vsock.
- `runtime/internal/agentstream`, `agentwire`, and `codexvm` retain one ordered
  App Server stream across the VMM replacement. Reconnects are generation
  bound, replay is deduplicated, and client-visible output has one total order.
- `runtime/internal/firecracker` owns exact-process lifecycle checks,
  peer-bound Unix/vsock endpoints, the fixed model relay, and API traces.
- `runtime/cmd/check-firecracker-codex-evidence` independently parses the
  retained result, VMM API calls, relay logs, bridge commitments, App Server
  records, payload manifest, repository bundle, snapshot hashes, process
  identities, canonical checkpoint object, final repository and delta, and
  event order. It does not import the live runner lifecycle.
- `runtime/cmd/control` publishes a private Unix socket for the active
  Firecracker generation. The callback reaches the existing Operation gateway
  through that socket without a bearer token. The first Cutover binds the
  source VM and repository; the second atomically binds the replacement VM,
  complete History head, checkpoint, final bundle, and host-derived delta.
- `runtime/cmd/check-firecracker-codex-control-evidence` is a second,
  standard-library-only checker. It independently recomputes the five-event
  History chain, Certificate and Requirement digests, VM-bound Operation
  identity and request hash, external receipt and durable commit, head-anchor
  checksum, and repository artifact bindings. It imports none of their live
  implementations.

The client-facing boundary remains stdin/stdout JSONL. No Firecracker-specific
branch is required in the App Server client.

## Current real execution

A fresh local KVM execution of the current source completed in 15.0 seconds
with these fixed inputs:

- Firecracker 1.16.1:
  `2fd0171309af7e24cf8dafc8a6f921c1434c49b5f9349bb996b7ed0a4deb8aa7`;
- Linux 6.1.155 kernel:
  `e20e46d0c36c55c0d1014eb20576171b3f3d922260d9f792017aeff53af3d4f2`;
- native Codex 0.147.0:
  `cb0a15567e9a60a5820d54b0f6ae86d504dc3805c1eab21a47f70e3eb7b73a40`;
- guest:
  `49cee411975645da7906a8c846f7f688f0b7e498a9f18de5c56cbd269fbefb72`;
- shim:
  `467e39dbe9c39e8129126d22e9798baac2b824dec0ed5f441ffc5fbdb5ab7e4e`;
- canonical Restate food-ordering repository:
  `8c815e42e1d5650feb40965c1a492caba24060297a7e285464fe487b6d335da2`
  (50,176 bytes, 37 entries, tree root
  `5023fab86509a198f38c6a81fec1b89f39404f4f65864dbd06855898098b1d8e`).

The run retained 23 lifecycle events, 20 hashed artifacts, 82 canonical bridge
commitments, and 357 App Server records. It created a 1 GiB memory snapshot;
both VMM PIDs were reaped. The final 37-entry bundle exactly matched the input
tree, as expected for this read-only model fixture. The host still produced and
verified a 160-byte, zero-operation delta bound to both tree roots. It also
retained a 1,541-byte canonical checkpoint object with SHA-256
`6ac1e9ae66c15a3ef3b4a1cae1456bbe259c46fcbc4d378c34a6e6ef9cd79387`.
The original shim, its runtime-retained copy, the result, and the first event
all carry the same hash.

The joined control path recorded exactly five events: initial Cutover,
Operation prepare, dispatch, success, and final repository-aware Cutover. The
Operation is owned by sandbox `firecracker-codex` and domain
`firecracker-codex-vm`. The external service durably recorded one delivery and
one commit. Calling the same stable callback through the replacement
generation returned `reused:true`; the external counts and History remained at
one commit and five events. The Firecracker checker returned
`{"schema":1,"valid":true}` and the joined checker returned
`valid:true`, History sequence 5, Operation
`op-a916d428972172262d64cb319440063299239010ad18456337a45848a7197090`,
one external commit, and `repository_edit:false`.
This is one observed functional execution, not a latency distribution or a
production-security result.

## Reproduction entry points

The real-KVM path is deliberately opt-in:

```sh
make runtime-firecracker-codex-build FIRECRACKER_BUILD_DIR=/private/build
go run ./runtime/cmd/firecracker-codex-payload --help
make runtime-firecracker-codex-repository \
  FIRECRACKER_CODEX_REPOSITORY_ARGS='-source /source -output /private/repository.bundle -result /private/repository.json'
python3 -m adapter.firecracker_codex_runtime_demo --help
```

After retaining a run, invoke the independent checker through:

```sh
make runtime-firecracker-codex-check \
  FIRECRACKER_CODEX_EVIDENCE=/private/runtime \
  FIRECRACKER_CODEX_ADAPTER_EVIDENCE=/private/adapter \
  FIRECRACKER_CODEX_PAYLOAD=/private/codex.squashfs \
  FIRECRACKER_CODEX_PAYLOAD_RESULT=/private/payload.json \
  FIRECRACKER_CODEX_RUNNER=/private/build/firecracker-codex-shim
```

For a run made with the five optional control-join arguments shown by
`python3 -m adapter.firecracker_codex_runtime_demo --help`, verify the complete
cross-system join with:

```sh
make runtime-firecracker-codex-control-check \
  FIRECRACKER_CODEX_EVIDENCE=/private/runtime \
  FIRECRACKER_CODEX_ADAPTER_EVIDENCE=/private/adapter \
  FIRECRACKER_CODEX_CONTROL_HISTORY=/private/control/runtime.history \
  FIRECRACKER_CODEX_HEAD_ANCHOR=/private/control/runtime.head \
  FIRECRACKER_CODEX_PAYMENT_HISTORY=/private/control/payment.history
```

The demo requires read/write access to `/dev/kvm`, checksum-pinned Firecracker
and kernel files, a prebuilt guest and shim, the read-only Codex payload, a
canonical repository bundle, separate empty evidence/workspace directories,
and no live account.

## Exact boundary and remaining work

The current slice is intentionally narrow:

- it protects exactly one dynamic-tool callback and one successful turn;
- the guest payload is not yet a normal build environment;
- the model fixture is local, fixed, and credential-free;
- Firecracker does not yet run through jailer, a dedicated host UID, or a
  chroot;
- the full snapshot is large, private, and may contain prompts or future
  credentials, so it must not be published as ordinary evidence;
- the checkers establish internal and cross-system consistency, not hardware
  attestation, and currently trust the supplied payload manifest for image
  contents; and
- this run exercises one successful retry-safe external Operation; it does not
  cover unknown outcomes, query recovery, concurrent callbacks, or arbitrary
  provider protocols inside this Firecracker path.

The next high-value increment is a maintained, writable build workload whose
Codex turn makes a nonempty repository delta and performs multiple protected
operations. That will test useful work, conflict handling, repeated boundaries,
and failure recovery rather than another synthetic VM lifecycle. Portable
certificates, jailer confinement, Claude, and a provider-independent adapter
remain later steps.
