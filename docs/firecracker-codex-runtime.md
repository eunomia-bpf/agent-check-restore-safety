# Firecracker Codex continuity runtime

**Status:** working real-KVM vertical prototype, 2026-08-16. The runtime now
supports both ordered native callbacks and ordinary Codex MCP calls across a
full-machine restore. One native Codex process, two Firecracker VMM
generations, a host-retained MCP journal, two external Operations, and one
durable History have been joined in a checked execution. It is not yet a
production sandbox or general agent runtime.

## What the system is

An ordinary Codex App Server client is given a temporary `codex` executable.
The client does not know that this executable starts a Firecracker runtime.
Inside the microVM, the exact native Codex binary runs against a read-only
payload and a workspace materialized from a canonical read-only repository
drive. The guest has no NIC and receives no account credential. A host-owned
model relay is the only model path. Codex is told that Firecracker is its
external sandbox, so file tools operate directly in the guest workspace while
the microVM remains the isolation boundary.

During one declared Codex turn, the runtime:

1. lets native Codex complete a declared workspace edit and a declared build
   command inside the same guest, then retains the first protected callback
   instead of exposing it to the client. The live gate refuses to invoke a
   protected handler unless both records are unique, ordered, and successful;
2. establishes a two-way stream checkpoint and drains the model path;
3. pauses the first VM, creates a full snapshot, sends `SIGKILL` to the exact
   first VMM, and waits for that child to be reaped;
4. starts a different VMM, loads the sealed snapshot while paused, installs
   authenticated host endpoints, resumes it, and reconnects the retained
   stream; and
5. exposes the first callback only after the restored guest is attached, then
   admits later ordered callbacks from the same turn. The host sends each one
   through a credential-free Unix socket owned by that exact sandbox
   generation; the guest cannot choose its identity, provider URL, method, or
   provider headers. Success is reported only after every matching callback
   result has entered the retained stream, the same Codex turn has completed
   successfully, that completion has reached the client, and client input has
   closed; and
6. sends an authenticated shutdown to the guest, freezes and empties the
   complete Codex cgroup, exports the resulting full repository tree, and
   derives the canonical delta on the host.

Firecracker supplies isolation and whole-machine snapshot/restore. It is a
replaceable mechanism, not the research claim. The runtime contribution is the
continuity boundary around it: external progress that a snapshot cannot erase
is joined with the History/Rule control plane and the repository state that a
replacement VM receives. This slice now performs that vertical join for a
bounded ordered set of real Codex callbacks.

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
- `runtime/cmd/mcp-operation-host` remains outside the VM restore domain. The
  guest contains only an untrusted relay. Guest PID 1 maps its fixed loopback
  port 7002 onto a generation-bound host relay, while the host serializes
  protected requests into one fsynced journal and one History order.
- `runtime/cmd/check-firecracker-codex-evidence` independently parses the
  retained result, VMM API calls, relay logs, bridge commitments, App Server
  records, payload manifest, repository bundle, snapshot hashes, process
  identities, canonical checkpoint object, final repository and delta, and
  event order. An optional workload contract checks the exact final-tree file
  outcome, nonempty delta, and hashes of the guest compiler and shell. The
  checker does not import the live runner lifecycle.
- `runtime/cmd/control` publishes a private Unix socket for the active
  Firecracker generation. The callback reaches the existing Operation gateway
  through that socket without a bearer token. The first Cutover binds the
  source VM and repository; the second atomically binds the replacement VM,
  complete History head, checkpoint, final bundle, and host-derived delta.
- `runtime/cmd/check-firecracker-codex-control-evidence` is a second,
  standard-library-only checker. It independently recomputes the ordered
  History chain, Certificate and Requirement digests, every VM-bound Operation
  identity and request hash, query observations or direct receipts, durable
  external commits, head-anchor checksum, repository artifact bindings,
  native file-change completion, and a successful declared build before the
  protected callbacks. It imports none of their live implementations.
- `adapter/check_firecracker_codex_mcp_evidence.py` independently joins the
  Codex MCP completions, MCP journal chain, binary History chain and external
  head, provider commits, host process identities, and the identical relay
  hash recorded on the host and in the guest payload manifest.

The client-facing boundary remains stdin/stdout JSONL. No Firecracker-specific
branch is required in the App Server client.

## Current MCP execution

The public MCP target completed on KVM with Firecracker 1.16.1, Linux 6.1.155,
and native Codex 0.147.0. Codex completed Operation A before the checkpoint.
The runtime then paused the VM, created a 1 GiB full snapshot, killed and
reaped the first VMM, loaded the snapshot into a different paused VMM, armed
both host relays, and resumed it. A new MCP tool session first replayed A and
received the exact original `operation_id` and `result_hash`; it then submitted
Operation B under a new identity. The deliberately non-idempotent provider
recorded exactly two deliveries and two commits, not three.

The run retained three guest-to-host MCP relay lifetimes across the two VMM
generations. The guest relay SHA-256 was
`83f65fe02dfc5bce7999504798f74cb76c06e4ab190fa61206786d4bbce71d90`,
and the offline checker proved that the same digest named the executable host
input and the only `bin/mcp-operation-relay` entry in the immutable payload.
The Firecracker checker returned `{"schema":1,"valid":true}`. The independent
continuity checker also returned `valid:true`, with three MCP completions, two
Operations, two provider commits, two VMM generations, and Codex 0.147.0.

This execution proves completed-call replay and safe admission of later work
across a full VM replacement. It does not yet snapshot while a provider write
is in flight.

## Earlier repository-edit execution

A retained local KVM execution of the repository-edit path completed in
16.6 seconds with these fixed inputs:

- Firecracker 1.16.1:
  `2fd0171309af7e24cf8dafc8a6f921c1434c49b5f9349bb996b7ed0a4deb8aa7`;
- Linux 6.1.155 kernel:
  `e20e46d0c36c55c0d1014eb20576171b3f3d922260d9f792017aeff53af3d4f2`;
- native Codex 0.147.0:
  `cb0a15567e9a60a5820d54b0f6ae86d504dc3805c1eab21a47f70e3eb7b73a40`;
- guest:
  `2a8f2421b996da3ec83a63825caee33f322ca0fd434f66a68d3ef59c6266a191`;
- shim:
  `fd4fc39459b2be845cd91dd9f9aaad26dd0f9a5b9808b21e8199a209fce2a671`;
- immutable payload:
  `faef1237b7d832ffa5f1c0cab5813833b5125cd2a8692f7df2d1cf5443a0d82e`,
  containing static esbuild 0.25.4
  (`93433b456cac3a454ee27403d3de9adce88d83e5439ba37e1471af54730c9ca7`)
  and a static shell
  (`dbac288c29ba568459550a2da9e7ae0ded6b1fc728ee9fad3044c44e62d6ac14`);
- canonical Restate food-ordering repository:
  `8c815e42e1d5650feb40965c1a492caba24060297a7e285464fe487b6d335da2`
  (50,176 bytes, 37 entries, tree root
  `5023fab86509a198f38c6a81fec1b89f39404f4f65864dbd06855898098b1d8e`).

The deterministic model asked native Codex to modify
`src/order-app/clients/payment_client.ts`: the edit removes payment tokens from
three log messages. The patch identity is
`d7bd3e573c91731b25e0cf3803b9438b310ba80c5d033937d0eec6416a054a36`.
Before exposing the protected callback, the same Codex turn compiled the
changed TypeScript file with the payload's esbuild. App Server retained the
exact command, its
`0a3eb7cbb19ca99ac481e793f04729e9b0bd9e9ed1437cff951fa7022d868677`
identity, exit code zero, and compiler output. The run retained 23 lifecycle
events, 20 hashed artifacts, 125 canonical bridge commitments, and 383 App
Server records. It created a 1 GiB memory snapshot;
both VMM PIDs were reaped. The final tree root is
`8b5d0ea59aac9ab63af747dc4a6520278201dc955637361895e0dc3cd5fd1e62`.
The host derived and reconstructed a 1,320-byte, one-operation delta; the final
bundle SHA-256 is
`aaa70c587f86852fb550222207b4b2eaf200afa1d2b9e385d17f1fee01976fbb`.
It also retained a 1,543-byte canonical checkpoint object with SHA-256
`6702cd8e21de786e126ab07e12e4953155ef4966019efa8e7bec06fcc23a7810`.
The original shim, its runtime-retained copy, the result, and the first event
all carry the same hash.

The joined control path recorded exactly nine events: initial Cutover; prepare,
dispatch, unknown outcome, and query-settled success for the first Operation;
prepare, dispatch, and direct success for the second; and final
repository-aware Cutover. Both Operations are owned by sandbox
`firecracker-codex` and domain `firecracker-codex-vm`. For the first Operation,
the external service committed and deliberately dropped the response; recovery
queried that durable fact instead of dispatching the write again. The second
Operation then committed normally in the same Codex turn. The service retained
exactly two durable commits. Their identities are
`op-a916d428972172262d64cb319440063299239010ad18456337a45848a7197090`
and
`op-812de3bd7ad0ccdafcd4398d9c193be1cce5e4810eaac1f5635dee1c28126d3f`.
The Firecracker checker returned `{"schema":1,"valid":true}` and the joined
checker returned `valid:true`, History sequence 9, two external commits, and
`repository_edit:true`. With the checked workload contract, the VM checker
also verified that all three safe log strings are in the final canonical
bundle, the token-bearing form is absent, and the declared compiler and shell
are the executables fixed by the payload manifest. The joined checker
independently verified the edit, successful build, two callbacks, query
recovery, direct receipt, and final Cutover order.
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
python3 -m adapter.firecracker_codex_mcp_runtime_demo --help
```

Pass
`--workspace-patch-file runtime/workloads/restate-food-ordering/hide-payment-token.patch`
and the workload contract's declared `--workspace-validation-command` for the
retained writable workload described above.

After retaining a run, invoke the independent checker through:

```sh
make runtime-firecracker-codex-check \
  FIRECRACKER_CODEX_EVIDENCE=/private/runtime \
  FIRECRACKER_CODEX_ADAPTER_EVIDENCE=/private/adapter \
  FIRECRACKER_CODEX_PAYLOAD=/private/codex.squashfs \
  FIRECRACKER_CODEX_PAYLOAD_RESULT=/private/payload.json \
  FIRECRACKER_CODEX_RUNNER=/private/build/firecracker-codex-shim \
  FIRECRACKER_CODEX_WORKLOAD_CONTRACT=$PWD/runtime/workloads/restate-food-ordering/workload.json
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
  FIRECRACKER_CODEX_PAYMENT_HISTORY=/private/control/payment.history \
  FIRECRACKER_CODEX_WORKLOAD_CONTRACT=$PWD/runtime/workloads/restate-food-ordering/workload.json
```

For the MCP path, `make runtime-firecracker-codex-mcp-demo` is the public KVM
entry point. After retaining the combined evidence directory, run both
independent checkers with one command:

```sh
make runtime-firecracker-codex-mcp-check \
  FIRECRACKER_CODEX_MCP_EVIDENCE=/private/combined \
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

- it protects one to eight ordered dynamic-tool callbacks in one successful
  turn; only the first callback is currently used as the snapshot barrier;
- the guest payload contains a real TypeScript compiler and static shell, but
  not yet the workload's complete dependency tree or test runner;
- the model fixture is local, fixed, and credential-free;
- Firecracker does not yet run through jailer, a dedicated host UID, or a
  chroot;
- the full snapshot is large, private, and may contain prompts or future
  credentials, so it must not be published as ordinary evidence;
- the checkers establish internal and cross-system consistency, not hardware
  attestation, and currently trust the supplied payload manifest for image
  contents; and
- this run exercises one query-recovered unknown outcome followed by one
  direct external Operation; it does not cover concurrent callbacks or
  arbitrary provider protocols inside this Firecracker path; and
- the MCP run checkpoints after A has settled. It validates exact replay and
  later admission after restore, but not an MCP call suspended inside an
  unknown provider outcome at snapshot time.

The next high-value increment is to put the same continuity protocol behind a
second agent runtime or sandbox backend without changing the client workflow.
That will test whether the boundary is genuinely portable rather than a Codex
and Firecracker special case. Portable certificates, jailer confinement,
Claude, and a provider-independent adapter remain later steps.
