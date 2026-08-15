# Step 0010: restore a complete Linux guest after a remote commit

**Gate:** BOOTSTRAP

**Date:** 2026-08-15

**Status:** restricted full-VM restore path complete; larger goal active

## Question

Can the same five-object runtime remain correct when the local state being
restored is not one process or service object, but an entire running operating
system?

The decisive case is a remote action that commits after the saved VM state but
before the VM is restored. The restored guest believes it has not made the
call. Host History and the remote service know that it may have committed.

## Real environment

The public runner boots the official Ubuntu 24.04 released cloud image under
QEMU 8.2.2. The image is fixed to release `20260725` and the SHA-256 published
in Ubuntu's `SHA256SUMS`:

```text
d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac
```

The retained run used TCG, 1 GiB of guest memory, two virtual CPUs, a q35
machine, one temporary qcow2 overlay, and guest kernel
`6.8.0-136-generic`. It required no root privilege and no KVM access.

## Enforced boundary

The QEMU command disables implicit NICs and adds exactly one user-mode NIC with
`restrict=on`. It defines two fixed guest forwards:

- `10.0.2.100:8000` to a loopback metadata server; and
- `10.0.2.100:8787` to the loopback Operation API.

There is no payment forward. The payment and control listeners, History, head
anchor, and payment commit file all live in a host temporary directory outside
the guest overlay. The guest attempts to reach payment through QEMU's ordinary
host address before both calls; both attempts must fail.

The metadata contains one stable call identity and the current Operation API
credential. It does not contain a payment credential or an alternate network
path.

## Executed restore

1. Boot the unmodified Ubuntu image through cloud-init.
2. Wait until the guest script reaches a gate immediately before its call.
3. Stop QEMU and issue `savevm before_operation` through QMP. This saves the
   running VM state and its qcow2 disk state.
4. Open the gate and resume. The guest cannot contact payment directly, so it
   invokes the Operation API.
5. Payment syncs one commit and deliberately drops the response. Host History
   records the Operation as `unknown`. The guest reports this state and waits.
6. Stop QEMU, issue `loadvm before_operation`, and resume. Guest RAM, devices,
   and disk return to the state before its first call. Host History and payment
   do not change.
7. The restored guest again fails its direct-payment probe and repeats the
   same call. The runtime retries the existing Operation, payment returns its
   durable receipt, and the guest receives `succeeded` before powering off.

## Observed evidence

The public command is:

```sh
make runtime-vm-demo
```

Two clean TCG runs completed. The final retained output was:

```json
{
  "accelerator": "tcg",
  "base_image_sha256": "d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac",
  "direct_payment_from_guest": "blocked_before_and_after_restore",
  "first_network_result": "unknown",
  "full_linux_guest": true,
  "guest_kernel": "6.8.0-136-generic",
  "history_outside_guest_restore_domain": true,
  "host_history_sequence": 6,
  "host_owned_restricted_network": true,
  "payment_outside_guest_restore_domain": true,
  "remote_commits": 1,
  "remote_deliveries": 2,
  "restored_operation": "succeeded",
  "snapshot_saved_before_operation": true,
  "whole_vm_restored": true
}
```

The runner also verifies the internal snapshot with `qemu-img snapshot -l`,
requires exactly one final succeeded Operation, requires exactly two payment
deliveries and one durable payment identity, and rejects a serial trace in
which either direct probe succeeds.

## Why this matters

Ordinary VM restore faithfully returns local computation to an earlier state.
That is precisely the problem once an external action has escaped. This path
shows that the host runtime can preserve the action's identity and meaning
across a whole-machine rollback without modifying QEMU, the Ubuntu kernel, or
the cloud image and without placing old recovery branches inside the guest.

The surprising visible result is:

> We restored the whole running machine to before a payment that had already
> committed, let the restored machine repeat the call, and still committed the
> payment once.

## Verification and honest boundary

Unit tests cover image download verification, failed digest cleanup, serial
marker waiting, and result extraction. All Go packages build, test, and pass
`go vet`. The complete VM run is a separate real-system gate because unit tests
cannot replace QEMU execution.

The host payment and control listeners run in the same orchestrator process in
this VM experiment; the prior container experiment already validates their
process and network separation. This step mediates one HTTP path, not arbitrary
block writes, GPU output, passthrough hardware, ioctls, or covert channels. It
uses a purpose-built guest action rather than Codex or a maintained application.
The runner pins Ubuntu's published hash but does not independently verify the
`SHA256SUMS.gpg` signature. The retained evidence is TCG; the KVM option is
implemented but was not used for the reported result.

The next cross-domain step is to put a real Codex task inside this guest and
route its tool or service Operation through the same host boundary, then join
that VM path with the separate order/payment deployment.
