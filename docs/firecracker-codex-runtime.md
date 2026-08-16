# Firecracker Codex continuity runtime

**Status:** working real-KVM research prototype, 2026-08-16. It is not yet a
production sandbox or an implementation of the complete History/Rule system.

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
5. exposes the callback only after the restored guest is attached. Success is
   reported only after the matching callback result has entered the retained
   stream, the same Codex turn has completed successfully, that completion has
   reached the client, and client input has closed; and
6. sends an authenticated shutdown to the guest, freezes and empties the
   complete Codex cgroup, exports the resulting full repository tree, and
   derives the canonical delta on the host.

Firecracker supplies isolation and whole-machine snapshot/restore. It is a
replaceable mechanism, not the research claim. The runtime contribution is the
continuity boundary around it: external progress that a snapshot cannot erase
must eventually be joined with the History/Rule control plane. This first
slice validates the process, transport, and evidence mechanics; it does not
yet perform that final join.

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
  identities, and event order. It does not import the live runner lifecycle.

The client-facing boundary remains stdin/stdout JSONL. No Firecracker-specific
branch is required in the App Server client.

## Current real execution

A fresh local KVM execution of the current source completed in 12.8 seconds
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
  `d9c8c55e30dfa1adbcf6b7ff054e6f21fa80d0582697444927a3c0bd02c1d5ea`;
- canonical Restate food-ordering repository:
  `8c815e42e1d5650feb40965c1a492caba24060297a7e285464fe487b6d335da2`
  (50,176 bytes, 37 entries, tree root
  `5023fab86509a198f38c6a81fec1b89f39404f4f65864dbd06855898098b1d8e`).

The run retained 23 lifecycle events, 19 hashed artifacts, 82 canonical bridge
commitments, and 358 App Server records. It created a 1 GiB memory snapshot;
both VMM PIDs were reaped. The final 37-entry bundle exactly matched the input
tree, as expected for this read-only model fixture. The host still produced and
verified a 160-byte, zero-operation delta bound to both tree roots. The original
shim, its runtime-retained copy, the result, and the first event all carry the
same hash. The independent checker returned
`{"schema":1,"valid":true}`. This is one observed functional execution, not a
latency distribution or a production-security result.

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
- the checker establishes internal consistency, not hardware attestation, and
  currently trusts the supplied payload manifest for image contents; and
- the callback is not yet a History-owned external Operation, so this run does
  not prove safe payment replay, Rule activation, or the paper theorem.

The next high-value increment is not another VM demo. It is to join the
host-derived delta, the existing Operation gateway, and an atomic History/Rule
change at the VM checkpoint. That makes the filesystem result and irreversible
external progress one committed transition. Portable certificates, jailer
confinement, repeated boundaries, Claude, and a maintained build environment
follow that vertical join.
