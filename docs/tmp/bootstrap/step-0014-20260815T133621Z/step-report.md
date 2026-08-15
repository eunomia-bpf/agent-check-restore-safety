# Step 0014: one History across Codex, services, and a full VM

Date: 2026-08-15 UTC

## Outcome

One real logged-in Codex App Server completed one purchase whose work crossed a
replaceable order service, a complete Ubuntu QEMU guest, and three separately
durable external services. Codex, order, and the VM issued three Operations to
one control service and one shared History:

- Codex charged payment;
- order reserved inventory; and
- the VM appended an audit record to ledger.

The run changed Rule v1 to v2, replaced the whole order container, restarted
the control process, and restored the complete VM from a QEMU snapshot. Payment
and inventory each committed once and lost their first response. Ledger
committed once and returned normally. The final totals were five deliveries
and three durable commits:

| Service | Deliveries | Commits | Paths observed |
|---|---:|---:|---|
| payment | 2 | 1 | two `/v1/charge` |
| inventory | 2 | 1 | two `/v1/charge` |
| ledger | 1 | 1 | one `/v1/charge` |

The replacement order process requested `reserve-v2` at `/v2/charge`. Its
stable call identity instead recovered the earlier Operation, so the runtime
used that Operation's frozen `reserve-v1` kind and `/v1/charge` target. The
restored VM repeated its stable audit call and received the result already in
History with `reused=true`; it did not redeliver to ledger. Codex received all
three completed results in its one pending tool callback and replied exactly
`DONE`.

This is the first functional vertical composition in the repository. It is a
system smoke test, not a performance result or the maintained-application
evaluation required by the research contract.

## Reproduction

The retained run used the public target with an explicit live-account output
directory and QEMU TCG:

```sh
make runtime-integrated-demo VM_ACCEL=tcg \
  INTEGRATED_DEMO_ARGS='--output-dir docs/tmp/bootstrap/step-0014-20260815T133621Z --model gpt-5.6-sol'
```

The target requires an existing `codex login`, may consume account quota, and
is deliberately excluded from ordinary verification. A new run creates a new
run identity and new Operation identities.

## Concrete system

- Codex was the real `codex-cli 0.147.0` App Server, model `gpt-5.6-sol`,
  provider `openai`, using the existing ChatGPT login. The retained protocol has
  one `complete_purchase` dynamic-tool call, one callback response, one
  completed turn, and final message `DONE`.
- The order, control, fixed ingress, payment, inventory, and ledger processes
  ran as separate hardened Docker containers. Their root filesystems were
  read-only, all capabilities were removed, and `no-new-privileges` was set.
- The VM was a complete Ubuntu 24.04 guest with kernel
  `6.8.0-136-generic`, Q35 machine type, two virtual CPUs, 1024 MiB memory, and
  the checksum-pinned base image SHA-256
  `d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac`.
- QEMU used TCG. The saved command records one disabled implicit NIC and one
  `restrict=on` user network with only metadata/gate and shared-control guest
  forwards.
- Payment, inventory, ledger, History, and the external History head used
  separate host-owned durable files outside the VM snapshot.
- Control loaded three independently scoped adapter credentials. The order
  container mounted only its own read-only credential, not the control
  credential directory.

The Codex container used a private temporary copy of `auth.json`. The runner
removed that copy after the tool call and before external work, observed that
the source file was unchanged, and recorded that all actor tokens were
distinct. The retained evidence contains no token or account credential.

## One shared History

The run identity was:

```text
run      = safe-change-integrated-1578928-3523f0c4
purchase = A-17-3523f0c4
Codex    = op-d94cfde088108ff7b33c98aedb7d27b1d5c49dee168552717e19d91414eef7a1
order    = op-c255fda4aa813124f95a6def57f54dd315a84b2b7749fce146d0e1fdb8d76bcc
VM       = op-2c63d5a0adc8123aed61a6119bbfa244adc333c4b7f8772baf19d62d15f61e99
```

The hash-linked History ends at sequence 15 with head:

```text
877b997d9092dfde27ba2ea02d12b7ae951b2d09e9aac202e558665f210b95cd
```

Its observed order is:

1. Activate Rule v1 for payment, inventory v1, and audit.
2. Record Codex payment as prepared, dispatched, then unknown after the lost
   response.
3. Record order inventory v1 as prepared, dispatched, then unknown after the
   lost response.
4. Record the VM audit as prepared, dispatched, then succeeded.
5. Against History head sequence 10, compile Rule v2 and record its activation
   at sequence 11. The v2 Requirement contains `reserve-v2`, while its Rule
   admits no new work because the three required results are already fixed by
   the earlier Operations.
6. Under the restarted control process, dispatch and settle the earlier Codex
   payment Operation.
7. Under the same restarted process, dispatch and settle the earlier order
   inventory v1 Operation.

The VM audit remains generation 1. Codex payment and order inventory recover
as generation 2 with a different control dispatch owner. All three Operations
are succeeded in `final-state.json` under Requirement v2.

## Changes and restore

The order container ID changed from
`9498359a0078f3efc1e26a9e19a61d892e413270c0288507b48c014bb2f5ddac`
to
`8ba1b66c78e939eb11bc5218b11dbc2e42e8db230129e35267885ba66e4cacf1`.
The control container remained the same durable deployment object, but its
process PID changed from `1581713` to `1608892`.

The QMP transcript records this exact client command order:

```text
qmp_capabilities
stop
savevm before_purchase
cont
stop
loadvm before_purchase
cont
```

The named internal snapshot appears in `vm/snapshots.txt`. Guest serial output
records a failed direct-effect probe before and after restore, one first audit
with `reused=false`, and the restored audit with `reused=true`.

## Enforced network paths

The saved Docker state records three network domains:

```text
Codex -> agent -> ingress -> application -> control -> effects
order ---------------------> application -> control -> effects
VM -> QEMU guest forward -> ingress ------> control -> effects
```

Codex joined only the agent network. Order joined only the internal application
network. Payment, inventory, and ledger joined only the internal effects
network. Ingress joined agent and application; control joined application and
effects. No effect service exposed a host port.

Two positive probes established the intended Codex-to-ingress and
order-to-control paths. Twelve negative probes then showed that both Codex and
order failed to reach payment, inventory, or ledger by either service name or
effects-network address. The VM's restricted QEMU network exposed no direct
effect forward.

These are enforced local Docker/QEMU boundaries and saved observations, not
signed remote attestation.

## Retained evidence

| Evidence | Recorded fact |
|---|---|
| `requirement-v1.json`, `requirement-v2.json` | exact old and new Requirements |
| `certificate-*.json`, `certificate-state-*.json` | History-bound Rule inputs and outputs |
| `checker-verdict-*.json` | standalone Certificate checker accepted v1 and v2 |
| `runtime.history`, `runtime.head`, `history.json` | binary shared History, external head, and API view |
| `payment.history`, `inventory.history`, `ledger.history` | one durable external record per Operation |
| `effect-stats.json` | five deliveries and three commits |
| `app-server.jsonl` | privacy-filtered real App Server process and protocol |
| `docker-inspect.json`, `docker-network-inspect.json` | container hardening and exact network membership |
| `network-probes.json`, `network-topology.json` | intended reachable paths and blocked direct paths |
| `control-after-restart-inspect.json` | restarted control process over retained state |
| `order-after-replacement-inspect.json` | replacement v2 order container |
| `vm/qemu-command.json` | privacy-filtered exact QEMU invocation |
| `vm/qmp-protocol.jsonl`, `vm/snapshots.txt` | whole-VM save/load commands and named snapshot |
| `vm/guest.serial.log`, `vm/result.json`, `vm-events.json` | guest behavior before and after restore |
| `*-unknown.json`, `*-recovered.json`, `settled-retries.json` | response loss, recovery, and result reuse |
| `credential-lifecycle.json` | separate tokens and temporary account-copy lifecycle |
| `teardown.json`, `logs/` | Compose and image cleanup return codes and service output |
| `result.json` | live runner summary derived from the files above |
| `independent-verdict.json` | downstream replay verdict derived without the live runner |

The binary History file SHA-256 is
`b78971f4194a9aa6f1da5869e3e9315f6d45e1c184011d22e6fd2978fc25833a`.
The App Server transcript SHA-256 is
`3d9b68b135333f0b225514a87f05c402cb31e395c9d3018d1f9890fd58850880`.
The QMP transcript SHA-256 is
`e178e914dc8994d2be740dbc2b3ce835d47b978b1b5fbae72173583235be6d09`.

## Verification status

Both Rule activations have retained `valid=true` verdicts from the separately
implemented Go Certificate checker. The live runner also rejected an
unexpected topology, direct network reachability, mismatched receipt, duplicate
commit, missing VM restore, changed account source, or unsuccessful teardown
before writing `result.json`.

The downstream checker then accepted the retained bundle and wrote
`independent-verdict.json` with `valid=true`. It does not import the live
runner. It independently replays the binary History and external head, reruns
both Certificate checks, derives all three Operation identities and request
hashes, joins the three durable effect records, and checks the saved Docker,
App Server, QEMU, QMP, serial-console, outcome, and timing evidence. The
account-free command is:

```sh
make runtime-integrated-check
```

Seven checker tests passed. In addition to accepting the retained run, they
require rejection after changing a binary History byte, the QMP `loadvm`
command, a Docker network's internal flag, the Codex tool identity, or the
inventory record from `/v1/charge` to a fabricated `/v2/charge`; a final test
checks the default verdict-writing path.

## Honest boundary

- The order, payment, inventory, and ledger services are purpose-built fixtures,
  not a maintained real application.
- Codex runs beside the full VM, not inside it; Claude is not implemented.
- This was one TCG run. It provides no KVM, repetition, performance, scale, or
  baseline result.
- The VM boundary covers the demonstrated HTTP path, not block devices, GPUs,
  passthrough devices, or arbitrary host interfaces.
- Docker and QEMU observations are local and unsigned; the host kernel, Docker
  daemon, QEMU, native Codex bundle, OpenAI provider, and effect services remain
  trusted.
- Control is not replicated, and remote receipts are not signed evidence.
- The bounded model has no end-to-end refinement proof for these concrete
  Codex, service, Docker, and QEMU executions.

No file under `docs/paper/` changed in this step.
