# Experiment Plan: make History the Firecracker start authority

## Admission and decision value

- Gate: **EXPERIMENT** for repository RQ4, “Is there a deployable
  algorithmic boundary?” No paper file may change during the experiment.
- Step 0022 already proved that official Claude, a complete Firecracker loss,
  ordinary HTTP, History recovery, and unmodified DeathStarBench can work in
  one run. It did not make the exact edit decision the exclusive owner of the
  VMM execution primitive: after Python performed a cutover, the cell still
  called Firecracker `InstanceStart` unconditionally.
- Step 0024 implemented that ownership for QEMU `cont`, but the full Ubuntu
  guest never reached the model endpoint. It produced no scientific result.
- This experiment asks the narrower and higher-value question: can a
  host-owned History decision be the only code path that starts a disposable
  Agent microVM, so two external histories give opposite, enforced outcomes
  for the same target and the same immutable Agent/runtime artifacts?
- Planned paper-value role: **decisive systems experiment for the remaining
  RQ4 enforcement gap**. The best alternative use of the same budget is
  transparent arbitrary-HTTPS mediation or a jailer/privilege-separation
  deployment. Those are important next boundaries, but neither establishes
  that the repository's exact decision can control a real VMM primitive; this
  experiment therefore has higher immediate decision value.
- A positive result closes a theory-to-system gap; it does not establish
  arbitrary I/O mediation, production isolation, fleet scheduling, or all of
  RQ4. A denied result that still starts a guest, a positive result that
  duplicates the application effect, or histories/targets that are not
  matched invalidates the experiment.

## Frozen hypothesis and conditions

- **H1 / effect exists:** an initial `activate` Certificate authorizes the
  source `InstanceStart`. Official Claude's reservation commits in
  DeathStarBench, the source VMM is killed before any response reaches the
  guest, and History reaches `prepared -> dispatched -> unknown`. An
  authoritative Mongo query settles the Operation as succeeded. Compilation
  of the target returns `activate`; after atomic Rule/binding cutover, one
  opaque permit authorizes the replacement `InstanceStart`. Replacement Claude
  reuses the result and completes. H1 therefore has two configured VMM
  processes, two authorized starts, one application delivery, and one Mongo
  row.
- **H0 / effect cannot exist:** an initial `activate` Certificate likewise
  authorizes one source start. Source Claude reaches the model and egress
  relays; the effect gate durably records a terminal pre-upstream fence and
  closes the request, so History reaches `prepared -> dispatched -> unknown`
  without an application delivery. An exact zero-row Mongo observation settles
  recovery as failed. The byte-identical target returns `impossible`. A second
  Firecracker process is fully configured and observed in state `Not started`;
  the same launch guard is invoked, denies its start, observes it still `Not
  started`, and reaps it. Zero guest `READY`, model, egress, application, and
  Mongo events are required specifically for this denied replacement process,
  not for the H0 source.
- **Unguarded control:** a distinct baseline-only launcher uses the same
  Firecracker, guest, payload, model, request, normalized machine
  configuration, and application, but has a different executable hash and no
  protected-deployment role. A source loss plus raw retry must execute two
  unguarded `InstanceStart` calls, complete, and create two rows.
- The frozen initial Requirement requires `reserved=1` and `finished=1`, with
  capacities `reservation=1` and `finish-slot=1`. Its `reserve` kind is
  non-retry-safe, queryable, and bound to the one effect URL and Mongo observer;
  its `finish` kind is retry-safe and bound to a local completion service. The
  frozen target retains the same results, capacities, and `finish` kind, but
  replaces `reserve` with a disabled, non-queryable kind that has the same
  costs/production and no executable target. Thus an already succeeded
  reservation lets `finished` remain achievable (`activate`), while a failed
  reservation leaves required `reserved` unreachable (`impossible`). Complete
  canonical JSON for both is retained as `requirement-v1.json` and
  `requirement-v2.json`; dynamic endpoint strings are selected once per
  execution before any lane and are identical across H1/H0. Their exact
  SHA-256 hashes are frozen in the run manifest before source launch.
- H1 and H0 use byte-identical target Requirement bytes. Within each
  repetition, H1, H0, and the control use the same hashes for the
  Firecracker binary, kernel, guest, read-only payload, Claude binary, BusyBox,
  and Bash wrapper. A normalized machine description freezes vCPU, memory,
  SMT, dirty-page setting, boot arguments, guest CID, drive attributes, tool
  profile, and all artifact hashes. Actual API records may substitute only the
  declared generation, random instance/session identity, and private API/vsock/
  evidence paths; the checker normalizes exactly those fields and rejects any
  other difference. Complete H1/H0 pre-recovery History must match after the
  checker substitutes only declared Operation, session, dispatch-owner, and
  host-instance identities. Their one recovery update may differ only in
  outcome-bound phase, result/fact hash, result body/reference, settlement,
  and consequent History head, all derived from the retained Mongo success or
  terminal-fence-plus-zero-row evidence. No other event or field may differ
  before target compilation.

## System change under test

- Factor the backend-independent decision checks from the QEMU-specific
  resume guard into a host lifecycle guard. Its request binds the independently
  checked Certificate, checked State, post-cutover History head and Rule,
  sandbox binding, concrete pidfd-verified VMM process, immutable artifact
  hashes, and canonical machine configuration.
- A new protected Firecracker History cell owns the API client. It may
  configure a VMM, but the
  guard owns its only `InstanceStart` callback. Authorization and start are
  serialized; immediately before consuming a one-use permit, the guard
  rereads live authenticated Control state and binding and revalidates process,
  artifacts, and configuration.
- Both initial source starts and target replacement starts use this path. An
  `impossible` Certificate creates no permit. The cell still exercises the
  same guard call and proves denial before `InstanceStart`; direct or repeated
  permit use must fail closed.
- The protected cell has no flag, mode, callback, or fallback that can select
  an unguarded start. The existing Claude cell is retained as the baseline-only
  launcher under a different executable name and hash; admission rejects that
  hash for every protected lane. Shared implementation helpers may configure
  artifacts and VMMs, but only the protected command owns the protected API
  client and its source contains one start call inside the guard callback.
- Enforcement claim and TCB are deliberately structural: the source-manifest-
  hashed protected cell is the only admitted runtime command that constructs
  the protected Firecracker API client. The Python driver, protected cell,
  Control, correctness kernel, Firecracker VMM, host Linux kernel, and same-UID
  host are in the TCB; a hostile same-UID process could discover and call
  `api.sock`.
  Filesystem secrecy is not claimed as a credential boundary. Moving the cell
  behind Firecracker jailer, a distinct UID, or a privileged daemon is required
  before claiming protection from a compromised driver. Claude, Firecracker,
  and DeathStarBench remain unmodified.

## Real assets and comparison

- Official Claude Code 2.1.233, Firecracker 1.16.1, Linux 6.1.155, and
  unmodified DeathStarBench Hotel Reservation 0.3.5 at commit
  `6ecb09706140f8730b5385c08f1386c654c3c526` with its complete 24-service
  definition and application-owned MongoDB.
- Claude uses its built-in Bash tool and ordinary HTTP. The deterministic
  local model chooses the fixed action but supplies neither edit decisions nor
  external truth.
- Each microVM has one vCPU, 1 GiB RAM, no NIC, no root disk, and one read-only
  payload. The registered host route and stable Operation identity are the
  only application path.
- The fresh unguarded control, launched by the separately hashed baseline-only
  command, is the main comparison. Step 0022 is prior supporting evidence, not
  substituted for a planned run.

## Metrics and independent oracles

- Primary safety/enforcement metrics: exact independent H1/H0 target
  Certificate decision; H1 source and replacement each have exactly one
  guarded `InstanceStart`; H0 source has exactly one guarded start while its
  configured replacement has none; the control source and replacement each
  have one unguarded start; H1/H0/control Mongo multiplicity is 1/0/2;
  protected task completion and application delivery count match the lane.
- Retained ground truth: binary History and head anchors, checked/projected/
  live State, Certificate bytes, sandbox bindings, Firecracker API JSONL,
  pidfd-bound process identity and reap, immutable artifact and machine hashes,
  guest gate/relay/model records, exact terminal fence, bounded Mongo facts,
  DeathStar adapter audit, and source/replacement Claude streams.
- The checker must import no producer driver. It independently reruns the
  Certificate checker, parses History, hashes artifacts/configuration, joins
  Mongo and fence facts, checks API order, and rejects any H0 guest/model/
  egress evidence from the denied replacement or any residual VMM.
- H0 additionally requires two authenticated Firecracker `GET /` observations
  reporting the replacement as `Not started`, one immediately before denied
  authorization and one after the failed start attempt, followed by exact VMM
  reap and a final independent zero-row/zero-delivery observation.
- Mutation tests cover Certificate/History heads, binding generation, artifact
  and configuration hashes, Firecracker PID/start identity, missing or extra
  `InstanceStart`, reused permits, terminal fence, Mongo facts, response-byte
  boundary, and VMM reaping.

## Runs and execution discipline

| Group | Repetitions | Required terminal result |
|---|---:|---|
| H1 guarded | 3 | `activate`, source + replacement start, task completes, 1 row, 1 delivery |
| H0 guarded | 3 | `impossible`, source starts, replacement stays `Not started`, 0 rows/deliveries |
| unguarded | 3 | two starts, task completes, 2 rows, 2 deliveries |

- A real preflight is one complete H1/H0/control triple against the live
  application, followed by the independent checker. It is not infrastructure
  startup or a unit-only test.
- At most three real preflight attempts may run. Every failed attempt remains
  retained with its exact cause and scientific disposition. The full matrix
  may start only after a reviewed, independently checked preflight passes and
  a source/admission manifest is sealed.
- One 90-minute deadline covers a preflight build, DeathStarBench deployment,
  and one complete triple. A full-run deadline is `3 * measured preflight + 15
  minutes`, bounded to 30 minutes--4 hours. A preflight creates six
  Firecracker processes and five actual starts; the three-repetition matrix
  creates eighteen processes and fifteen starts. Each process has one vCPU and
  1 GiB, and all execute serially against one 24-service deployment.
  Cleanup reaps every exact cell runner and Firecracker process and removes
  experiment-owned containers/networks. Any accepted run that needed cleanup
  repair is invalid.
- No paid API or cloud service is used.

## Fixed commands and retained paths

- Preflight attempt N:
  `sg kvm -c 'make runtime-firecracker-history-preflight FIRECRACKER_HISTORY_PREFLIGHT_EVIDENCE=docs/tmp/bootstrap/step-0025-20260817T080834Z/experiment-firecracker-history-start-authority/preflight-attempt-N'`.
- Independent preflight check:
  `make runtime-firecracker-history-check FIRECRACKER_HISTORY_EVIDENCE=docs/tmp/bootstrap/step-0025-20260817T080834Z/experiment-firecracker-history-start-authority/preflight-attempt-N`.
- Seal a passing preflight:
  `make runtime-firecracker-history-admit FIRECRACKER_HISTORY_PREFLIGHT_EVIDENCE=docs/tmp/bootstrap/step-0025-20260817T080834Z/experiment-firecracker-history-start-authority/preflight-attempt-N`.
- Full matrix: `sg kvm -c 'make runtime-firecracker-history-demo'`.
- Full check: `make runtime-firecracker-history-check`.
- Accepted raw path:
  `docs/tmp/bootstrap/step-0025-20260817T080834Z/experiment-firecracker-history-start-authority/raw/`.
- Failed attempts remain in sibling `preflight-attempt-N/` directories and are
  never resumed or copied into accepted evidence.

## Completion and interpretation

- Complete only if all planned lanes reach their declared state, the
  independent checker and regression suite pass, H1/H0 share an exact target,
  H0 invokes the real guard and its replacement has no `InstanceStart`, H1 has
  no redispatch, the unguarded control duplicates, stale/reused authority
  fails, and every VMM is reaped.
- Positive interpretation: for one registered plaintext HTTP action, the same
  host correctness kernel that reasons over irreversible effects can directly
  control a real microVM execution primitive without Agent or application
  changes. Firecracker is a replaceable containment backend, not the source of
  correctness.
- Negative, contradictory, or mixed results are retained and reported without
  weakening the hypothesis. A fresh result reviewer must approve evidence and
  scope before documentation or paper claims change.
- Expected commands will be new
  `runtime-firecracker-history-{preflight,admit,demo,check}` Make targets. Raw
  evidence, if admitted, belongs under this experiment directory; regression
  gates are Python syntax/tests, `bash -n`, `go test ./...`, changed-package
  race tests, `go vet ./...`, and `git diff --check`.
