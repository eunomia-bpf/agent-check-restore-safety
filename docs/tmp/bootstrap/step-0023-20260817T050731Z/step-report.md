# Step 0023: history-dependent full-QEMU Agent restore

Status: incomplete at real preflight, 2026-08-17T06:10:00Z. Phase:
BUILD_AND_EVALUATE. Gate path: EXPERIMENT, returned to orchestration before a
full run.

## Admitted question

The reviewed experiment asked whether one host-owned History and edit checker
could control the actual resume of an unchanged official Agent in a complete
Ubuntu QEMU/KVM VM against an unchanged 24-service DeathStarBench deployment.
H1 and H0 were designed to share the same sealed checkpoint and target bytes,
with only an authoritative external-result fact changing `activate` to
`impossible`; a native restore would expose duplicate execution.

The frozen plan and reviews are under
`experiment-qemu-agent-history-restore/plan.md` and `plan-review.md`.

## System implementation

The step implemented, but did not yet validate end to end:

- a complete qcow2 plus named QEMU snapshot containing official Claude Code
  2.1.233 in Ubuntu 24.04;
- a QEMU source/restore supervisor with sealed copy verification, restricted
  fixed guest forwards, QMP protocol retention, and an exclusive resume path;
- a one-use VM resume guard bound to Certificate, activated History, target,
  checkpoint, machine configuration, QEMU process identity, sandbox binding,
  and the published Unix endpoint;
- a durable terminal pre-upstream fence that makes exact zero-row recovery
  conclusive for the H0 lane;
- an H1/H0/native driver over the unmodified DeathStarBench Hotel Reservation
  graph and real MongoDB; and
- an independent evidence checker that recomputes Certificates, Mongo facts,
  checkpoint hashes, QMP state transitions, and guard outcomes.

## Preflight disposition

All three allowed real preflights failed before any Agent or application
request, so there is no accepted scientific result:

1. the QMP Unix path exceeded Linux's 108-byte limit;
2. the independently owned sandbox Unix path exceeded the same limit; and
3. the source supervisor confused QEMU's initial halted `prelaunch` state with
   the later explicit-`stop` state named `paused`.

Each failure and repair is retained in
`experiment-qemu-agent-history-restore/preflight-attempts.md` and in the three
attempt directories. The third attempt proves that the base VM booted, the
complete qcow2 and named snapshot were sealed, the 24-service application and
Control endpoint became healthy, the lane copy matched the seal, and QEMU
loaded it under `-S -loadvm before_agent`. QMP then reported exactly
`status=prelaunch,running=false`; the erroneous literal check terminated the VM
before `cont`.

The repaired implementation now distinguishes the initial
`snapshot-loaded-halted` state (`prelaunch`, not running) from a later explicit
pause (`paused`, not running), and the checker requires both exact states. The
independent amendment reviewer approved that causal correction but prohibited
a direct full run because no end-to-end preflight succeeded.

## Verification and routing

- focused short Unix-socket Control startup: pass (87-byte endpoint);
- VM supervisor, resume guard, and sandbox host Go tests: pass;
- Python syntax and repository whitespace checks: pass at disposition;
- real end-to-end preflight: **not passed**;
- full three-repetition matrix: **not run**; and
- paper files: unchanged.

Step 0023 makes no claim and must not be cited as a positive result. The next
route is a separately reviewed execution that inherits the repaired system,
discloses all three Step 0023 failures, and first earns a new end-to-end
preflight before any full run.
