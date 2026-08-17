# Experiment Plan: RQ4 full-VM history-dependent Restore

## Research Question

- RQ exactly as written in the repository evaluation contract: **RQ4: Is
  there a deployable algorithmic boundary?**
- Specific uncertainty tested here: can the same host runtime make the exact
  edit decision and enforce it at a complete-VM boundary, rather than merely
  preserving one Operation after a sandbox crash? In particular, can one
  byte-identical QEMU checkpoint and one byte-identical target Requirement be
  accepted after an authoritative query finds a durable external result but
  rejected after the same query proves that the result cannot exist?
- Why the answer matters: the existing system has separately demonstrated
  exact Requirement changes, full QEMU restore, official Agents, and a
  maintained microservice. It has not connected all four in one execution.
  Without that connection, the formal answer is not yet the control plane for
  a real Agent restore.

## Paper-Value Admission

- Planned role: **decisive systems experiment for the theory-to-runtime gap
  within RQ4**. It is not a production-performance or arbitrary-I/O result.
- Largest credible paper story this experiment could unlock: an unchanged
  official Agent runs inside a complete Ubuntu QEMU/KVM machine and invokes an
  unchanged maintained application through ordinary Bash HTTP. The host owns
  the execution record, external-operation recovery, edit checker, Rule
  activation, VM checkpoint, and sandbox generation. A single durable fact
  outside the VM changes the exact Restore answer even though the checkpoint
  bytes and target Requirement are identical; an accepted Restore resumes the
  Agent without duplicating the fact.
- Strongest reviewer reject argument or load-bearing uncertainty addressed:
  the current repository could be read as several disconnected demos. The
  Operation gateway preserves effects, while the checker changes abstract
  Requirements, but no real Agent VM restore is conditional on the checker's
  history-dependent answer.
- Independent evidence added beyond existing runs: Step 22 cold-replaces a
  Firecracker VM under the same Requirement. This experiment changes the
  Requirement, uses an actual QEMU whole-machine checkpoint, requires opposite
  answers for two histories sharing that checkpoint and target, and makes VM
  resume conditional on atomic Rule-and-generation activation.
- Why the result is not tautological, already settled, or dominated: a matched
  native QEMU restore starts from the same checkpoint and replays the same
  ordinary Agent request without History. It must duplicate application state.
  A reject-only lane shows that safety without useful continuation is not the
  proposed result. Application-owned MongoDB facts, not the checker output,
  determine whether the external result exists.
- Paper decision if positive: the system can claim one end-to-end realization
  in which an exact history-dependent edit answer controls a complete Agent VM
  and a maintained application, while preserving useful continuation after an
  unknown external outcome. This is a scoped causal vertical, not by itself a
  complete answer to RQ4 or a production-readiness claim.
- Paper decision if contradictory, mixed, or inconclusive: if the two histories
  do not receive opposite independently checked answers, if accepted Restore
  duplicates the reservation, if native replay does not duplicate, or if VM
  resume can bypass the exclusive guard, the current architecture does not
  realize the paper's edit boundary and must be redesigned before a larger
  OS/runtime claim.
- Best alternative experiment and why this one has higher decision value: a
  common launcher across process, container, Firecracker, and QEMU would improve
  packaging and portability but would not connect the theorem to a real edit.
  A symbolic-solver scale run would strengthen the backend while leaving the
  more important implementation gap untouched.

## Expected And Alternative Outcomes

- Current expected answer:
  - **H1 / durable result:** DeathStarBench commits the reservation, but a
    barrier withholds every response byte. The source VM is then killed. The
    normalized History is `prepared -> dispatched -> unknown`; an authoritative
    Mongo query finds the exact result and records success. The target
    Requirement removes the old producer but still requires its result, so the
    checker returns `activate`. The runtime installs the Rule and replacement
    sandbox binding while QEMU is paused, attaches the endpoint, and grants one
    bound resume authorization. Restored Claude reuses the saved result and
    finishes with one Mongo row.
  - **H0 / result proven absent:** the identical Agent request reaches the same
    normalized `prepared -> dispatched -> unknown` History. A fault gate
    durably records a terminal pre-upstream abort before any Mongo request or
    response byte, and the source VM is killed. The authoritative query combines
    that fence with an exact zero-row result and records failure. The same
    target checker returns `impossible`; the driver attempts the same guarded
    resume and is denied. MongoDB remains empty, and the terminal fence plus
    stale-generation rejection prevents a later commit.
  - **native replay:** source and restored Agent executions use the same QEMU
    checkpoint and request identity but bypass History. Both reach the
    application, producing two Mongo rows before the task completes.
- Strongest competing explanation: the receiver, QEMU snapshot machinery, or
  deterministic model prevents duplication independently of the runtime. The
  matched native lane therefore uses the same Agent binary, model protocol,
  checkpoint, request, application, failure point, and VM resources.
- Result that would contradict the expectation: any H1 rejection, H0
  activation, accepted-restore duplicate, raw single row, stale-generation
  delivery, Agent-visible source response, or resume before the durable Rule
  cutover.

## Published Precedent And Real Assets

- Closest published protocol: output commit and RIFL motivate stable operation
  identity; QEMU supplies whole-machine save/restore; DeathStarBench supplies
  the maintained application. The paper's exact checker supplies the
  history-dependent admission decision. These components are reused rather
  than individually claimed as new.
- Official system/model/data/benchmark/tool and version:
  - official Claude Code 2.1.233 from the already verified signed release;
  - QEMU 8.2.2 with KVM and the checksum-pinned Ubuntu 24.04 cloud image;
  - unmodified DeathStarBench Hotel Reservation 0.3.5 at commit
    `6ecb09706140f8730b5385c08f1386c654c3c526`, with its 24-service definition;
  - the repository's independently checked Requirement compiler, durable
    History, query recovery, Rule cutover, and generation-bound sandbox socket.
- What is reused: the QEMU whole-VM runner and QMP evidence, signed Claude
  artifact, ordinary Bash fixture, host HTTP route, DeathStar effect adapter
  and Mongo observer, safe-change CLI/control API, and existing external
  evidence checkers.
- Necessary deviations or custom glue: the QEMU guest downloads the already
  verified Claude binary from its fixed metadata channel before the checkpoint;
  one supervisor coordinates a reusable base checkpoint, model forward,
  egress forward, compile/cutover, and QMP pause/load/resume. Claude and
  DeathStarBench source remain unchanged.

## Comparison

- Proposed system or method: official Claude in full QEMU VM -> ordinary Bash
  HTTP -> restricted QEMU guest forward -> generation-bound host route ->
  History gateway -> DeathStarBench, with target compilation, durable
  Rule/sandbox cutover, endpoint attachment, and a one-use guarded QEMU resume.
- Main baseline and competing position: **native QEMU restore and replay**.
  It represents the conventional position that restoring the machine and
  retrying the Agent is sufficient when the receiver does not provide
  idempotency. It uses the same checkpoint and external application but no
  host History mediation.
- Why the main baseline needs a matched run instead of citation alone: whether
  this exact DeathStarBench request and QEMU failure window duplicate is an
  end-to-end property of the selected application and execution path.
- Controls or ablations, labeled separately:
  - **H0 reject control:** same checkpoint, target bytes, Agent request,
    Operation identity, and normalized History as H1; only the authoritative
    external-result fact differs;
  - **stale-generation control:** an old host route submitted after cutover
    must fail without another application delivery;
  - **resume-enforcement control:** QMP is reachable only through an exclusive
    guard. Its one-use authorization binds the independently checked
    Certificate and History head, target hash, sealed checkpoint and canonical
    machine configuration, QEMU PID/start identity, replacement generation and
    host binding, and endpoint publication. H0 attempts `cont` through the same
    guard and must be denied;
  - **network control:** QEMU uses `restrict=on`; Claude receives no
    DeathStarBench address or credential and can reach only fixed metadata,
    model, and egress forwards;
  - receiver idempotency is cited, not run, because adding it modifies the
    maintained application and answers a different question.
- Conclusion if the main baseline matches or wins: if native replay does not
  duplicate, the comparison is non-discriminating; if the proposed path cannot
  continue, the host edit boundary provides no useful advantage here.
- Information, tuning, and compute fairness: proposed and native lanes use one
  source checkpoint artifact, exact Agent/request/model/application versions,
  identical vCPU/memory, and the same no-response failure barrier. H0 and H1
  also use alpha-equivalent request and Operation identities and byte-identical
  targets; only the fault gate's terminal fact and consequent query result
  differ. The native lane omits History mediation and the Rule cutover.
- Split or leakage rule: the independent checker reads retained QMP, Agent,
  History, Rule, proxy, adapter, and Mongo records only after execution. It
  recomputes the two edit answers and Mongo multiplicities without importing
  the experiment driver.

## Workloads And Metrics

- Real workload: one-night reservation through DeathStarBench Hotel
  Reservation, initiated by official Claude's built-in Bash tool inside a full
  Ubuntu QEMU/KVM guest.
- Primary metrics:
  - independently checked edit decision for H1 and H0;
  - exact matching MongoDB reservation documents per lane;
  - restored Agent terminal completion;
  - application deliveries per stable logical request.
- Correctness check or ground truth: MongoDB exact documents and their hashes
  are retained as the external oracle. The H0 zero-row fact is accepted only
  together with the durable terminal pre-upstream fence. Barrier
  acknowledgments, exact QMP commands/replies, and `/proc` identities prove
  the full-VM pause/load/resume order; raw Claude streams prove the ordinary
  Bash call and final result; binary History and Certificates prove H1/H0
  decisions and the durable Rule/binding cutover. Proxy byte counts prove no
  source response reached Claude.
- Repetitions, seeds, and uncertainty: three H1 proposed executions and three
  native replay executions with distinct logical identities, plus three H0
  decision controls. Each H1/H0/native triple is derived from the same sealed
  checkpoint artifact. The model endpoint is deterministic; repetitions test
  asynchronous QEMU/network cuts, not model quality.
- Cost estimate: one DeathStarBench deployment, three base QEMU boots and nine
  short KVM lanes at two vCPU/1 GiB, local deterministic model traffic, and no
  paid API or cloud service.

## Planned Runs

| Run group | Role | Workload | System/method | Repetitions | Decision consequence |
|---|---|---|---|---:|---|
| H1 | proposed | Claude + DeathStar reservation | commit/lost response, query recovery, target edit, durable cutover, guarded whole-VM Restore | 3 | `activate`, task completes, one row |
| H0 | control | same sealed checkpoint, request, unknown state, and target | terminal pre-upstream abort, query recovery, attempted guarded Restore | 3 | `impossible`, resume denied, zero rows |
| native | main baseline | same | QEMU Restore and Agent replay without History | 3 | task completes, two rows |
| stale/resume/network | controls | all applicable lanes | generation probe, QMP ordering, restricted forwards | all | any bypass or wrong order invalidates the run |

## Execution

- Authoritative command or workflow: `make runtime-qemu-agent-restore-demo`
  starts/reuses the pinned real assets, runs the full matrix, and retains raw
  evidence. `make runtime-qemu-agent-restore-check` validates a retained run
  without Docker, KVM, or the producer driver.
- Real preflight case: one H1 lane reaches a real Mongo commit, proves zero
  response bytes to the source VM, settles the unknown Operation by the Mongo
  query, receives `activate`, performs cutover while paused, loads the sealed
  checkpoint, and finishes in the restored VM with one row.
- Enforced activation order: start the lane QEMU paused and load the named
  snapshot; compile and independently validate the Certificate; durably cut
  over the Rule and sandbox binding as one transaction; attach and positively
  probe the replacement endpoint; mint the bound one-use resume authorization;
  then issue QMP `cont`. Endpoint attachment and resume are fail-closed later
  steps, not part of the atomic Rule/binding transaction.
- Full completion rule: every planned lane reaches its declared terminal
  state; the independent checker recomputes H1/H0 as `activate`/`impossible`;
  H1/native/H0 have exactly 1/2/0 retained Mongo documents; H1 completes with
  no redispatch after Restore; native completes after two deliveries; H0 was
  unknown before query, explicitly attempts resume, is denied, and can never
  commit later; stale generations fail; the exact guarded QMP command/reply,
  endpoint readiness, and QEMU reap are present; repository regressions pass.
- Raw-result path:
  `docs/tmp/bootstrap/step-0023-20260817T050731Z/experiment-qemu-agent-history-restore/raw/`.
- Fixed commands:
  - preflight: `make runtime-qemu-agent-restore-preflight`;
  - full matrix: `make runtime-qemu-agent-restore-demo`;
  - retained-evidence check: `make runtime-qemu-agent-restore-check`;
  - regressions: `make runtime-test` and `go test ./...` from `runtime/`.
- Checkpoint or recovery approach: each repetition creates one internal QEMU
  snapshot after Claude installation and before Agent execution, then closes
  the base QEMU process. The complete qcow2 file and canonical machine
  configuration are hashed and sealed. A copy is made for every lane and its
  digest is verified before QEMU can open it. Each lane starts paused with
  `-S`, loads the exact named snapshot, and exposes QMP only to the guard.
  Failed preflights remain outside the final `raw/` directory.

## Interpretation

- Positive result: the execution record, not VM bytes or the target alone,
  determines whether Restore can be implemented; the same exact answer that
  protects the edit also controls a useful whole-VM continuation.
- Negative or contradictory result: retain it outside the paper and redesign
  the edit/VM cutover boundary; do not weaken the hypothesis.
- Mixed or inconclusive result: any nonidentical checkpoint triple, missing
  Mongo truth, QMP ordering gap, nondiscriminating native lane, or partial
  matrix makes the experiment incomplete or invalid.
- Target paper figure or table: one diagram showing the common checkpoint
  splitting into H0/H1/native histories, plus a three-row table with decision,
  Mongo multiplicity, Agent completion, and Rule-before-resume ordering.

## Reproducibility Notes

- Record the exact Git revision, QEMU executable/hash/version, KVM device
  identity, Ubuntu image hash, Claude signed-release record, DeathStar commit
  and image IDs, checkpoint hashes, QEMU commands, and all runtime binaries.
- Use a distinct application identity per repetition. H0 and H1 use a
  declared opaque renaming of that identity so the independent checker can
  normalize it before comparing requests, Operations, and target bytes; source
  and restored executions within each lane retain exactly one identity.
- The deterministic local model controls only Claude's tool choice. It is not
  the edit decision, safety mechanism, or external oracle.
- The experiment covers one registered plaintext HTTP action, one exact
  target change, and one full-VM restore protocol. It does not establish
  arbitrary HTTPS, device/DMA mediation, remote attestation, replicated
  control, fleet scheduling, or production performance.
