# Firecracker backend

This backend exercises safe change across two real Firecracker processes. It
uses KVM and virtio-vsock, but deliberately gives the guest no network device,
credential, provider address, or root disk.

## Machine-readable preflight

Asset setup and admission are separate. First fetch the pinned assets and build
the static guest, then run the prototype check with the account that would run
the backend:

```sh
make runtime-firecracker-fetch runtime-firecracker-build
sg kvm -c 'make runtime-firecracker-preflight'
```

The command writes one JSON report to stdout and exits zero only when all seven
prototype checks pass: Linux amd64, read/write `/dev/kvm` with KVM API version
12, the exact pinned Firecracker binary and version, the exact pinned kernel, a
static `CGO_ENABLED=0` guest, and a canonical current-user-owned directory with
mode 0700. It opens KVM only to query the API version; it starts no microVM.

The stricter level is also machine-checkable:

```sh
make runtime-firecracker-production-preflight
```

It additionally checks the exact pinned jailer, a root invoker, a dedicated
non-root UID/GID, cgroup v2 and an empty controller-enabled parent, a trusted
chroot base and resource-staging directory, and root-owned paths that are not
group- or world-writable for every admitted asset. These checks follow
Firecracker's pinned
[production-host recommendations](https://github.com/firecracker-microvm/firecracker/blob/v1.16.1/docs/prod-host-setup.md)
and [jailer contract](https://github.com/firecracker-microvm/firecracker/blob/v1.16.1/docs/jailer.md).
The checker only reports; it never creates an account, changes ownership, or
edits cgroups.

The checked root-owned asset paths are trusted sources, not an immutability
guarantee. A production launcher must control updates to them, place
per-instance copies inside the jail, and give the dedicated UID/GID only the
permissions each guest resource needs; that staging path is part of the
currently failing runtime-integration check.

The report separates `production_host_ready` from `production_ready`. The
second is deliberately false today, even on a fully prepared root host,
because `firecracker-demo` still starts Firecracker directly. There is no
override that can turn that missing launch path into a pass. A future gate must
verify that the runner actually uses the pinned jailer with concrete cgroup and
resource limits, per-instance chroot resource placement, a new PID namespace,
privilege drop, default seccomp, and bounded guest-controlled output. The
current cgroup checks establish the cgroup v2 mount flags and the configured
parent's shape; they do not prove effective delegation or that a launcher
applies limits.

The current guest has no NIC or rootfs block image. That removes guest IP egress
from this prototype, but it does not by itself decide whether a production
host-process threat model should add a network namespace. The kernel,
initramfs, snapshot, and sockets still have to be placed inside each jail by a
future launcher.

Use `FIRECRACKER_PREFLIGHT_ARGS` or
`FIRECRACKER_PRODUCTION_PREFLIGHT_ARGS` to supply explicit installed paths and
identity/directory flags. See all flags with:

```sh
(cd runtime && go run ./cmd/firecracker-preflight -help)
```

## Run the real-KVM smoke test

From the repository root:

```sh
make runtime-firecracker-kvm-test
```

That one command downloads checksum-pinned assets, builds the static guest and
host runner, then runs the opt-in KVM test. It requires Linux x86-64, Go,
`curl`, Python 3, and read/write access to `/dev/kvm`. It does not require root.
If group membership is recorded but not active in the current login, run:

```sh
sg kvm -c 'make runtime-firecracker-kvm-test'
```

The smoke test supplies a local strict Operation endpoint so it can isolate the
Firecracker process, snapshot, and vsock mechanisms. It is real VMM execution,
not the retained end-to-end control-service result or a performance benchmark.

## What the first backend enforces

- The protocol requires Firecracker 1.16.1 or newer. This executable slice
  admits exactly the pinned 1.16.1 binary and its snapshot/vsock reconnect fix.
- The guest is one `CGO_ENABLED=0` Go binary running as PID 1 in a deterministic
  `newc` initramfs. The archive contains `/init`, `/request.json`, mount-point
  directories, and `/dev/console`; there is no root block device.
- No NIC, TAP, IP address, or guest-visible provider route is configured.
- The guest sends exactly `call_id`, `kind`, and `body` over AF_VSOCK CID 2,
  port 8787. A separate host gate on port 8000 carries `READY`, `GO`, and the
  final result.
- The first microVM is paused before the snapshot. After its first result, it
  remains blocked until the host stops that exact Firecracker process.
- A fresh Firecracker process loads the snapshot with `resume_vm=false` and a
  generation-specific `vsock_override`. The host installs the replacement
  relay before resume; the restored request must reuse the recorded Operation.

This is not yet a production sandbox. Firecracker's built-in seccomp remains
enabled, but the runner does not use `jailer`, dedicated UID/GID, chroot,
cgroup or resource limits, bounded guest-controlled output, or a network
namespace. The no-NIC configuration establishes guest network isolation for
this test; production claims require an implemented launcher and an explicit
host-process threat model.

## Build and evidence targets

Fetch or revalidate only the pinned host assets without opening KVM:

```sh
make runtime-firecracker-fetch
```

Build the static guest and runner into the current user's cache:

```sh
make runtime-firecracker-build
```

The runner is the lower-level component used by a retained shared-control run.
It requires an existing host-owned sandbox socket, the strict request, a private
empty evidence directory, and the explicit `start`, `pause`, `restore`, and
`resume` commands on stdin. See its exact flags with:

```sh
(cd runtime && go run ./cmd/firecracker-demo -help)
```

Check a retained directory independently, without starting Firecracker:

```sh
make runtime-firecracker-check \
  FIRECRACKER_EVIDENCE=/absolute/path/to/evidence
```

## Pinned assets

[`assets.lock.json`](assets.lock.json) fixes the Firecracker archive, extracted
Firecracker and jailer binaries, snapshot format, and official Firecracker CI
guest kernel by URL, size, and SHA-256. [`fetch-assets.sh`](fetch-assets.sh)
rejects unsafe archive paths, extracts only the two required regular files,
replaces a corrupt cached extraction, and verifies both Firecracker and jailer.
The public Make target refuses to execute the fetcher unless both files are
tracked and match `HEAD`; direct script execution bypasses that evidence guard.
The default cache is:

```text
~/.cache/safe-change-runtime/firecracker
```

The pinned guest kernel is used only with the initramfs; no downloaded rootfs
or mutable guest disk is involved.
