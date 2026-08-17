# Experiment Plan: execute the repaired full-QEMU Restore vertical

## Admission and provenance

- Gate: **EXPERIMENT** for repository RQ4, “Is there a deployable
  algorithmic boundary?”
- This is a separately admitted execution, not a fourth Step 0023 preflight.
  Step 0023 built the system but exhausted three preflights before any Agent or
  application request. Its complete failure record is retained at
  `../../step-0023-20260817T050731Z/experiment-qemu-agent-history-restore/`.
- Step 0024 inherits only the repaired implementation. It makes no use of a
  Step 0023 outcome, because no Step 0023 scientific outcome exists.
- No paper file may change during this experiment. A positive result may
  update implementation/evaluation documentation only after result review.

## Research question and decision value

- Can one host-owned History and exact edit decision control whether an
  unchanged official Agent may resume from a complete VM snapshot, while the
  same checkpoint bytes and same target Requirement receive opposite answers
  under two different external histories?
- This is the highest-value remaining vertical because the repository has
  separately shown exact edit decisions, full VM restore, official Agents, and
  maintained microservices, but has not made the edit decision the exclusive
  authority for a real Agent VM resume.
- A positive result closes one theory-to-runtime gap: the runtime can preserve
  useful work after an unknown external outcome and can also refuse an unsafe
  whole-VM continuation. It does not establish arbitrary I/O, production
  performance, fleet deployment, or a complete answer to RQ4.
- A negative result—wrong decision, duplicated H1 effect, nonduplicating native
  replay, QMP bypass, inconclusive H0, or mismatched checkpoints—requires a
  redesign and cannot be reframed as partial success.

## Frozen hypothesis and conditions

- **H1 / durable result:** Claude's reservation commits in DeathStarBench, but
  the source VM receives zero response bytes and is stopped. History reaches
  `prepared -> dispatched -> unknown`; an authoritative Mongo query finds the
  exact result and settles success. The target removes the old result producer
  while still requiring that result. The independently checked decision is
  `activate`; Rule plus sandbox binding cut over; the replacement endpoint is
  attached; one bound resume permit authorizes the sole QMP `cont`; restored
  Claude reuses the result, completes, and Mongo contains exactly one row.
- **H0 / result impossible:** the same unknown Operation state is paired with
  a durable terminal pre-upstream fence and an exact zero-row Mongo query.
  Recovery settles failure. The byte-identical target receives `impossible`.
  An actual call through the same resume guard is denied before any QMP
  `cont`, and Mongo remains empty.
- **Native baseline:** the same sealed checkpoint and Agent request bypass
  History. Source and restored executions both reach DeathStarBench, Claude
  completes, and Mongo contains exactly two rows.
- H1 and H0 differ only in the independently observed external-result fact and
  its consequent recovery event. H1, H0, and native use the same sealed
  checkpoint within each repetition. H1 and H0 use byte-identical target
  Requirements. The checker compares the complete first four H1/H0 History
  events and complete initial model requests after replacing only operation,
  session/client-device, dispatch-owner, and host-instance identities; it also
  requires the same canonical machine configuration.

## Real assets and boundary

- Official Claude Code 2.1.233, SHA-256
  `55d281096f57d411ebbdd94dbf5e9ff3accb7c05713e37348c2c11d4b83bf9d9`.
- QEMU 8.2.2 with KVM and checksum-pinned Ubuntu 24.04 image SHA-256
  `d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac`.
- Unmodified DeathStarBench Hotel Reservation 0.3.5 at commit
  `6ecb09706140f8730b5385c08f1386c654c3c526`, using its complete 24-service
  definition and real MongoDB.
- Claude and DeathStarBench source are unchanged. Claude uses its built-in Bash
  tool and ordinary HTTP. The deterministic model chooses only that fixed
  tool action; it does not supply an edit decision or external truth.
- QEMU uses a complete qcow2, q35, 2 vCPU, 2048 MiB, KVM, `restrict=on`, and
  only fixed metadata, model, and egress guest forwards. The guest receives no
  DeathStarBench address or credential.

## Sealing and enforced order

1. Boot the base Ubuntu VM, install and hash the pinned Claude artifact, stop
   QEMU, create named snapshot `before_agent`, quit and reap QEMU, then hash the
   complete qcow2 and canonical machine configuration.
2. Copy the sealed qcow2 for each lane and verify its full digest before QEMU
   can open it.
3. Start QEMU with `-S -loadvm before_agent`. After the QMP greeting, require
   exactly `status=prelaunch,running=false`. This event is
   `snapshot-loaded-halted`; QEMU documentation defines it as an initialized VM
   for which no restored vCPU has executed since this QEMU process loaded the
   named snapshot.
4. For a source lane only, issue `cont`; after the external barrier, issue
   `stop` and require exactly `status=paused,running=false`, then `quit` and
   reap QEMU.
5. Recover the unknown Operation from Mongo truth (plus the H0 terminal fence),
   compile and independently validate the target Certificate, and atomically
   cut over Rule plus sandbox binding.
6. Attach and positively probe the replacement endpoint. These are fail-closed
   steps after the durable cutover, not part of its atomic transaction.
7. While restored QEMU remains in `prelaunch`, read `/v1/state` and
   `/v1/sandbox-bindings` from the live authenticated Control process. Bind a
   one-use authorization to those facts, the checked Certificate, exact History
   head and target, sealed checkpoint and machine configuration, QEMU
   PID/start/executable/argv identity, the device/inode/size/hash of the lane
   qcow2 actually held open by that QEMU process, replacement binding, and exact
   endpoint device/inode/health.
8. The host supervisor owns the private QMP socket. In a guarded restore, its
   only `cont` path is the guard's callback. The guard repeats every live
   Control, process, disk, binding, and endpoint check immediately before it
   consumes the permit and calls that callback. H0 invokes the same guard with
   no valid permit and must reach `quit` with no `cont` in the trace.

## Metrics and independent oracles

- Primary: independently recomputed H1/H0 decision; exact Mongo documents per
  lane; restored Agent completion; application delivery count; presence or
  absence of guarded QMP `cont`.
- Retained ground truth: exact bounded Mongo documents and row hashes; durable
  H0 terminal-fence bytes; binary History and head anchors; Certificate and
  projected checked State; QMP command/reply JSONL including exact run states;
  QEMU `/proc` identity and reap; checkpoint and machine hashes; Unix endpoint
  identity; relay byte counts; Agent serial/model records; application audit.
- The checker pins Claude and Ubuntu digests, QEMU/QEMU-img/netcat hashes, the
  exact QMP 8.2.2 greeting, and hashes of freshly rebuilt runtime binaries. It
  joins unknown, checked, projected, current, manifest, and Certificate History
  points to exact raw frame hashes and verifies the target-cutover event's exact
  Certificate and binding bytes.
- The checker imports no producer-driver code. It independently hashes the
  checkpoint, reruns the Certificate checker, parses History, joins Mongo and
  adapter facts, checks exact QMP order and state transitions, and checks the
  one-use guard evidence.
- The checker reads the raw relay file rather than producer summaries and has
  mutation tests for History/head, terminal fences, Mongo documents, relay
  bytes, QMP order/state/`cont`, checkpoint/copy identity, live process/disk,
  endpoint/binding, Agent serial/session, stale-generation rejection, process
  reaping, and source/admission hashes.
- Any missing primary oracle, producer-only assertion, residual live QEMU,
  nonzero source response bytes, or inability to reconstruct a decision makes
  the result invalid.

## Runs and resource discipline

| Group | Repetitions | Expected terminal result |
|---|---:|---|
| H1 protected | 3 | `activate`, task completes, 1 Mongo row, 1 delivery |
| H0 deny | 3 | `impossible`, actual resume denied, 0 rows, 0 deliveries |
| native | 3 | task completes, 2 rows, 2 deliveries |

- Each H1/H0/native triple shares one sealed checkpoint. Distinct triples use
  distinct logical operation identities.
- Real preflight is one complete H1/H0/native triple with all final oracles and
  the independent checker, not merely successful infrastructure startup.
- At most three Step 0024 real preflights may run. Every failure remains under
  this step with its command, exact cause, repair, and scientific disposition.
- The full three-repetition matrix may start only after one complete preflight
  and its independent retained-evidence check pass. The pass creates a sealed
  admission record binding the complete tracked-and-untracked source manifest,
  independent checker, Certificate-checker binary, preflight results, and
  measured duration. Any later byte change invalidates the gate.
- The driver writes an atomic lane-stage record and the launcher retains a
  heartbeat across clone, build, deployment, execution, and final retention at
  least every 35 seconds. The checker joins both heartbeat endpoints to the
  complete execution clock and requires an intentional, zero-status monitor
  stop. It stops on the first failed lane. A preflight has
  one preparation QEMU plus six source/restore QEMU launches; the full matrix
  has three preparation QEMUs plus eighteen source/restore launches.
- One deadline covers clone/build/deployment as well as the Agent matrix. The
  preflight timeout is two hours. The full-run timeout is derived from the
  measured preflight duration as `3 * duration + 15 minutes`, bounded to
  30 minutes--4 hours. Timeout first interrupts the driver so its `finally`
  path terminates the complete `vm-demo` process group, then escalates through
  bounded TERM/KILL grace periods. Every VM runner is an independent process
  group and session and records its PID, start time, and live cmdline hash.
  QEMU also receives a parent-death kill signal. Cleanup independently scans
  every retained runner session even after its leader exits, finds exact runner
  descendants and QEMUs, reaps residuals, and rejects any run that
  needed this repair. Docker cleanup is time-bounded. A failed or
  interrupted run is never resumed into accepted evidence;
  a new accepted run starts with a new empty evidence directory and MongoDB.
- No paid API or cloud service is used. All QEMUs use 2 vCPU/2 GiB and share one
  local DeathStarBench deployment per run.

## Fixed commands and paths

- Preflight attempt N:
  `sg kvm -c 'make runtime-qemu-agent-restore-preflight QEMU_AGENT_RESTORE_PREFLIGHT_EVIDENCE=docs/tmp/bootstrap/step-0024-20260817T060908Z/experiment-qemu-agent-history-restore-execution/preflight-attempt-N'`
- Preflight check:
  `make runtime-qemu-agent-restore-check QEMU_AGENT_RESTORE_EVIDENCE=docs/tmp/bootstrap/step-0024-20260817T060908Z/experiment-qemu-agent-history-restore-execution/preflight-attempt-N`
- Seal a passing preflight for full execution:
  `make runtime-qemu-agent-restore-admit QEMU_AGENT_RESTORE_PREFLIGHT_EVIDENCE=docs/tmp/bootstrap/step-0024-20260817T060908Z/experiment-qemu-agent-history-restore-execution/preflight-attempt-N`
- Full matrix: `sg kvm -c 'make runtime-qemu-agent-restore-demo'`.
- Full check: `make runtime-qemu-agent-restore-check`.
- Accepted raw path:
  `docs/tmp/bootstrap/step-0024-20260817T060908Z/experiment-qemu-agent-history-restore-execution/raw/`.
- Regressions: Python syntax and checker tests; `bash -n`; `go test ./...`;
  race tests for changed Go packages; `go vet ./...`; `git diff --check`.

## Completion and interpretation

- Complete only if a reviewed preflight passes, every full lane reaches its
  declared terminal state, the independent checker passes without producer
  imports, H1/H0/native rows are exactly 1/0/2 in all repetitions, H1 performs
  no restored redispatch, H0 attempts and is denied resume, native duplicates,
  stale generations fail, and all QEMU processes are reaped.
- A fresh result reviewer must audit the raw evidence, plan compliance,
  checker independence, and failure history before any result is accepted.
- Positive interpretation is limited to one registered plaintext HTTP action,
  one exact target edit, one official Agent, one maintained application, and
  one complete-QEMU backend. It demonstrates a real enforcement vertical, not
  general complete mediation or production readiness.
- Any mixed or incomplete matrix returns to orchestration with no paper claim.
