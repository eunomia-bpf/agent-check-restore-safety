# Step 0018: crash-safe KVM sandbox restore with pinned execution inputs

Date: 2026-08-16 UTC

## Outcome

One real logged-in Codex App Server, one replaceable order service, and one
complete Ubuntu guest issued three Operations into one durable History. The VM
used KVM and a QEMU whole-machine `savevm`/`loadvm` cycle. It held no runtime
credential and supplied only `call_id`, `kind`, and `body`; QEMU forwarded those
bytes to a private Unix endpoint whose binding was owned by control.

The run paused QEMU after the VM's first external Operation, published Rule v2
and sandbox generation 2, replaced the order process, and sent `SIGKILL` to
control. The killed process exited 137. Its generation-2 socket inode remained
at mode 0600 but refused connections. Reopening control removed that inode and
did not attach the binding recovered from History. QEMU then loaded the saved
VM while still paused. A fresh Certificate and generation-3 Cutover completed
before QEMU resumed.

The final external facts were:

| Service | Deliveries | Commits | Paths observed |
|---|---:|---:|---|
| payment | 2 | 1 | two `/v1/charge` |
| inventory | 2 | 1 | two `/v1/charge` |
| ledger | 1 | 1 | one `/v1/charge` |

The replacement order process requested `reserve-v2` and `/v2/charge`, but its
stable call identity recovered the frozen v1 Operation. The restored VM retried
the same audit identity and received `reused=true`; ledger saw no second
delivery. Codex received all three results and replied exactly `DONE`.

## Reproduction

The retained live-account run was launched from a clean detached worktree at
Git revision `9bc184a81b2b34be96fe83e154f97262969a389f`:

```sh
sg kvm -c 'make runtime-integrated-demo VM_ACCEL=kvm \
  INTEGRATED_DEMO_ARGS="--output-dir \
  /home/will/agent-check-restore-safety/docs/tmp/bootstrap/step-0018-20260816T125801Z"'
```

The account-free independent check is:

```sh
make runtime-integrated-check
```

## Concrete execution

- Codex was `codex-cli 0.147.0`, provider `openai`, model `gpt-5.6-sol`, using
  the existing ChatGPT login through the real App Server protocol.
- QEMU was 8.2.2. The guest used KVM, Q35, two vCPUs, 1024 MiB memory, Ubuntu
  kernel `6.8.0-136-generic`, and the pinned base-image SHA-256
  `d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac`.
- The base image was copied into the run-private 0700 directory, verified while
  copying and again after close, and used from its 0600 private copy. QEMU did
  not reopen the shared cache path.
- The QEMU network had `restrict=on`, no implicit NIC, one loopback metadata
  forward, and one Unix-socket forward to the host sandbox endpoint. It had no
  TCP forward to control or any effect service.
- The exact retained guest request has three fields. The retained guest script
  contains no bearer token, adapter token path, provider target, domain,
  generation, or host instance identity.
- Socket observations record a 0700 parent, 0600 endpoints, UID 1001, healthy
  generations 1--3, the stale generation-2 inode after `SIGKILL`, and `ENOENT`
  after control reopened.
- Codex and order failed 12 direct DNS/IP probes to the effect network. The VM
  failed its direct ledger probe before and after restore.

## Paused restore order

The retained QMP trace contains 10 client commands and their responses:

1. negotiate QMP capabilities;
2. stop QEMU and confirm `paused`;
3. save `before_purchase` and resume;
4. after the first Operation, stop QEMU and confirm `paused` again;
5. load `before_purchase` and confirm that QEMU remains `paused`;
6. resume only after the generation-3 endpoint is published.

The five runner events are joined to the raw QMP clocks. The checker rejects a
load, status, Cutover, or resume order that differs from this sequence.

## One History

The run identity is `safe-change-integrated-1732127-3aff342b`; the purchase is
`A-17-3aff342b`. History ends at sequence 16 with head
`8f4ccd049ae23e7bb703187a28e2b18777afbfc0ab82b7c4d19fe175d52c8e3d`.

The exact event order is:

1. atomically publish Rule v1 and sandbox generation 1;
2. record Codex payment as prepared, dispatched, then unknown;
3. record order inventory as prepared, dispatched, then unknown;
4. record VM audit as prepared, dispatched, then succeeded;
5. while QEMU is paused, publish Rule v2 and generation 2;
6. kill and reopen control without attaching the replayed binding;
7. load the VM snapshot while QEMU remains paused;
8. publish a fresh Rule version and generation 3, then resume QEMU;
9. dispatch and settle the frozen payment and inventory Operations under the
   replacement control owner.

All three prepared Operations retain their bounded request bytes. The sandbox
Operation identity includes the stable sandbox ID but not its host generation,
so a valid replacement can recover the same result while another sandbox or an
adapter credential cannot claim it.

## Execution provenance

The producer began under `python3 -I`, recorded 140 committed Python/runtime
files, and rejected dirty producer files. Go builds and the Docker build used a
private `git archive` of the recorded revision. The immutable Docker image ID
was joined to every original and replacement container.

The live `vm-demo` process and live QEMU process were each checked through an
open `/proc/<pid>/exe` file descriptor. Their device, inode, and bytes matched
the executable opened before launch. The QEMU command was also read from
`/proc/<pid>/cmdline` and compared argument by argument. Recorded identities
include:

```text
source tree       3f7fcad4194bca2d22dae5fe22f20c9e1858bcf920df3fc803300b123773171e
vm-demo           7a73f102228a472c6e7e4a05a31d7740b4b83bfca5399f1457e0a462a5b4bfe2
QEMU              8a35ccba41582fc6c38b9df85fc9e35fa1d42f414d2d7d8090ee9b2f5e7c0854
qemu-img          634320b91165669917123e8e79cce1c4d00cee0a4aa4d662d7c0a8186479b3fb
nc.openbsd        2a6fac3d98e090468962ef18003cb8b89fbffa7219917ca12567d5e42b156948
Docker image      sha256:f6da3c6881261f477cea8b948f6571c5ef030dd5d3525806e3612c565b1f52f3
```

## Independent verification

`independent-verdict.json` has `valid=true`. The checker does not import the
live runner. It:

- replays all 16 binary History frames and the external head;
- reruns three Certificate checks at their exact History heads;
- checks all three Cutover bindings and active states;
- derives Operation identities, stored requests, request hashes, and receipts;
- joins three durable effect records and the five-delivery/three-commit facts;
- checks the Docker graph, 12 negative probes, raw App Server protocol, exact
  guest input and script, host-tool hashes, private base-image evidence, live
  process identities, 26 QMP records, serial markers, and socket clocks.

Eight producer tests and 15 checker tests pass. The 13 evidence mutations cover
History bytes, QMP load, Docker isolation, Codex tool identity, effect paths,
guest route and bearer fields, TCP control forwarding, socket mode, `SIGKILL`
exit status, the private base-image claim, and both live executable hashes.

Key artifact SHA-256 values are:

```text
runtime.history       16f1438af02c52c5f3de432f50fb591a262d36303748341f92f50446bc222daa
app-server.jsonl      aa30dd1a3444144a302f878c1054ebff02110fdc81b3d546ea902aef5514244b
qmp-protocol.jsonl    a6a01f06b9fa7d754842e33999f3f527fb57039ed6fad90b774477cbc6a34175
guest-script.sh       9e7d037910649b552b8b1ebaa1f20ec18f6d4253527f78620842756dbef94b4a
control-crash.json    db8aa6cf73e30ed9b029fbd5af3b51fd3b4c8ec9f287f489f5b2e6ef26a036e3
```

## Honest boundary

- This proves one concrete control-owned endpoint and KVM/QEMU restore path. It
  is not a performance, repetition, scale, or availability result.
- Socket mode, ownership, absence, process identity, and tool hashes are local
  observations on a trusted host, not remote attestation. A malicious process
  running as the same Unix UID is outside the endpoint threat model.
- The source, build, image, and executable records are internally joined
  provenance. They are not a signed SLSA/in-toto statement or a reproducible-
  build proof.
- QEMU snapshot reuse can duplicate arbitrary guest state. The demonstrated
  claim is only that the stable audit Operation did not create a second remote
  commit; it is not whole-guest rollback safety.
- The fixture effect services are not a maintained application. Firecracker,
  jailer confinement, vsock reset, disks, GPUs, passthrough devices, and
  arbitrary host interfaces are not yet implemented or tested here.
- Docker, QEMU, the host kernel, control, the native Codex bundle, the provider,
  and effect services remain trusted. Control is not replicated and receipts
  are not signed.
- There is not yet an end-to-end refinement proof connecting this concrete
  execution to the bounded model.

No file under `docs/paper/` changed in this step.
