# Step 0024 plan review

## Round 1 — revision required

The independent reviewer found the experiment scientifically promising but not
yet executable. The following findings were blocking:

1. Both resume-guard passes used State and bindings copied into a manifest
   instead of authenticated reads from the live Control process.
2. The permit named the sealed base checkpoint but did not prove that the QEMU
   process held open the exact per-lane `restore.qcow2`; process identity also
   omitted live argv.
3. The independent checker did not yet replay binary History, verify its
   external head anchor, join the H0 terminal fence, use raw relay bytes, or
   check complete process/guard/timeline equality.
4. There was no checker mutation suite.
5. H1/H0 matching covered selected State fields rather than the complete
   normalized four-event History, initial model requests, and machine config.
6. The run plan understated the workload: a three-repetition matrix launches
   three preparation QEMUs and eighteen source/restore QEMUs. It lacked measured
   duration, heartbeat, stop-loss, and an enforced preflight-to-full gate.
7. Source provenance omitted untracked implementation files and allowed the
   checker or source to change after preflight.

The reviewer accepted the Step 0023 disclosure, the exact
`prelaunch,false`/`paused,false` semantics, the private QMP boundary, and the
basic H1/H0/native design. No Step 0024 QEMU or Docker execution was permitted
after this review.

## Revision response

- The guard now reads live authenticated `/v1/state` and
  `/v1/sandbox-bindings` in both its authorization and resume pass.
- Live process identity includes `/proc/PID/cmdline`; a disk identity records
  path, device, inode, size, and pre-open hash, and each pass proves that the
  same QEMU process still holds that inode open.
- The checker independently validates History frames/hashes/head anchors, exact
  H0 fences and Mongo facts, raw relay bytes, machine config, checkpoint copies,
  live QEMU/process/disk identity, endpoint/binding joins, serial/model records,
  stale-generation failure, process reaping, and temporal order through QMP
  `cont`.
- The mutation suite now attacks every listed evidence family and the
  preflight admission/source hashes.
- A complete tracked-and-untracked source manifest is retained and independently
  recomputed. A full matrix requires a sealed passing-preflight record bound to
  that source root, both checkers, results, and measured duration.
- The plan now states all 21 full-run QEMU launches, atomic stage progress,
  35-second heartbeats, duration-derived deadline, bounded cleanup, and no
  accepted resume of partial evidence.

Round 2 must review the revised plan and implementation before any real
preflight begins.

## Round 2 — revision required

The reviewer confirmed that the round-1 live-state, binding, disk/argv,
History-model comparison, relay, fence, source, admission, heartbeat, and run
count blockers were substantially repaired. Four remaining blockers prevented
execution:

1. The stale-generation call selected tuple element zero and then attempted to
   unpack that integer, so H1 could not reach guarded restore.
2. Deadline accounting began after infrastructure setup; termination did not
   fully prove bounded process-group and residual-QEMU cleanup.
3. The checker did not independently pin externally supplied Claude, Ubuntu,
   QEMU, or freshly built runtime artifacts.
4. Raw History hashes, Certificates, projected State, checked State, current
   State, and manifest points were checked separately rather than joined to the
   exact same raw events. Mutations did not cover these final joins.

Again, no real QEMU, KVM, Docker, or benchmark execution was permitted.

## Round 2 revision response

- The stale-generation response now retains and unpacks the complete HTTP
  `(status, body)` tuple.
- One monitor now covers clone, build, deployment, Agent execution, and final
  retention. Timeout enters bounded INT/TERM/KILL cleanup. Event-process failure
  kills the complete `vm-demo` process group, and an independent PID+cmdline
  checker rejects accepted evidence if any exact QEMU survived or required
  cleanup. Docker teardown is individually time-bounded.
- The checker pins official Claude and Ubuntu digests, QEMU/QEMU-img/netcat
  hashes and versions, the QMP 8.2.2 greeting, the image/Claude fields in every
  machine config, and the actual runtime binaries against a fresh current-source
  build.
- The checker now joins unknown State to raw event 4; checked State,
  Certificate, and projection to raw recovery event 5; current State and
  manifest to the raw head; and H1's exact Certificate/binding bytes to raw
  cutover event 6. New mutations cover wrong-history Certificates, external
  assets/QMP versions, model bytes, deadline/heartbeat records, and residual
  cleanup.

Round 3 must approve the revised tree before the first preflight.

## Round 3 — revision required

The reviewer accepted the stale-response, live-Control, raw-History joins,
machine asset pins, and exact seven-QEMU-per-repetition accounting, but found
four remaining execution-admission defects:

1. A parent-shell signal was not by itself a bounded deadline for every
   foreground clone, build, deployment, and retention command.
2. SIGKILL paths still used unbounded waits; fallback cleanup addressed the
   Python driver and recorded QEMUs but not surviving `vm-demo` process groups.
3. The checker did not join a live QEMU's executable and complete argv to the
   pinned QEMU artifact and canonical machine configuration, and the QMP
   package comparison admitted suffixes.
4. A single heartbeat could pass; its endpoints were not joined to the full
   execution clock, and unexpected monitor death was not fatal.

No real QEMU, KVM, Docker, build, or benchmark execution was permitted.

## Round 3 revision response

- Every potentially blocking Git, Docker, Compose, HTTP, manifest, cleanup,
  and retention command now runs in a `timeout`-owned process group using the
  one absolute deadline. The Agent driver runs as its own session and fallback
  escalation targets that complete process group.
- Every `vm-demo` runner records its process-group identity and live command
  hash next to its QEMU evidence. Python waits after TERM/KILL are bounded, and
  the independent residual helper discovers and, on failed runs, terminates
  both exact runner groups and exact QEMU processes. Accepted evidence requires
  seven of each per repetition and no residual or repair.
- The checker independently reconstructs the complete QEMU argv from machine
  configuration and the pinned netcat path, requires equality with both the
  declared and `/proc`-observed command, joins the live executable to the fixed
  QEMU SHA-256, and requires the exact QMP package string.
- Accepted heartbeats must contain at least two records, have at most 35-second
  gaps, and cover both endpoints of the complete execution. The monitor has an
  explicit intentional-stop record with exit status zero; unexpected exit is
  fatal. Mutation tests now attack argv, executable digest, QMP package suffix,
  heartbeat endpoints, and monitor failure.

Round 4 must approve the revised tree before the first preflight.

## Round 4 — revision required

The reviewer accepted all Round-3 repairs but found one remaining launch-window
gap. Residual cleanup keyed a runner only by its leader PID and command hash.
If `vm-demo` exited after starting QEMU but before retaining QEMU process
evidence, its leader could disappear while an unrecorded QEMU survived in the
same session. PID-only cleanup could then report no residual.

No real QEMU, KVM, Docker, build, or benchmark execution was permitted.

## Round 4 revision response

- Linux now assigns every QEMU launched by `vm-demo` a `SIGKILL` parent-death
  signal, so loss of the runner cannot leave that QEMU alive through the
  launch/record window.
- Runner evidence now binds PID, process group, session, process start time,
  command hash, and executable hash. Cleanup enumerates every non-zombie member
  of that retained session whose start time is not older than the runner. It
  does so even after the leader PID has disappeared, terminates exact remaining
  members on failed runs, and requires the session to become empty.
- `_EventProcess.close` signals the recorded process group even when its leader
  has already exited. A regression test forks an orphaned member in a new
  session, reaps the leader, and proves that cleanup still discovers it.

Round 5 must approve the revised tree before the first preflight.

## Round 5 — approved

The independent reviewer confirmed that the Round-4 launch-window blocker is
closed. QEMU has parent-death termination; runner evidence binds PID, process
group, session, start time, command, and executable; cleanup scans retained
sessions after leader exit; and the checker requires all seven runners and
seven QEMUs per repetition with no residual or repair. The bounded deadline,
monitor coverage, exact executable/argv pins, and raw History joins remain
consistent.

This approval admits only the first real preflight. It does not pre-accept any
result. The reviewer executed no KVM, Docker, build, or benchmark command.
