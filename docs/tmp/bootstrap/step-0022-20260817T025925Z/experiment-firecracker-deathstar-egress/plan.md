# Experiment Plan: RQ4 Firecracker-to-DeathStarBench egress

## Research Question

- RQ exactly as written in the repository evaluation contract: **RQ4: Is
  there a deployable algorithmic boundary?** The current paper does not label
  its questions as RQs; this experiment tests its deployability claim without
  changing the paper's scientific contract.
- Specific uncertainty tested here: can an unmodified vendor Agent use an
  ordinary built-in network tool, rather than a declared MCP tool or SDK, to
  reach an unmodified maintained microservice through a host-owned boundary;
  can that boundary preserve one logical external Operation across complete
  source-VMM loss and a clean replacement VM?
- Why the answer matters: the current Codex and Claude results mediate only
  declared MCP calls. If ordinary built-in tools can bypass the runtime, the
  claimed low-adoption, OS/runtime direction is not yet a real system boundary.

## Paper-Value Admission

- Planned role: **decisive systems experiment for the ordinary-tool mediation
  gap within RQ4**. It does not settle all of RQ4 or production deployability.
- Largest credible paper story this experiment could unlock: one concrete
  execution spans an official Agent, a complete disposable Linux microVM, a
  generation-bound host runtime, a running full maintained DeathStarBench
  Hotel Reservation deployment, and application-owned MongoDB truth. The
  reservation need not traverse every service in that deployment. The Agent and source
  VMM may disappear after an irreversible reservation while the replacement
  still completes without duplicating it.
- Strongest reviewer reject argument or load-bearing uncertainty addressed:
  the repository contains several disconnected demonstrations, but no one run
  proves that a normal Agent built-in action is completely mediated across a
  real multi-service application and a VM failure boundary.
- Independent evidence added beyond existing runs: unlike the MCP runs, the
  protected action is a built-in Bash HTTP request; unlike the existing
  DeathStarBench run, the caller is official Claude inside Firecracker and the
  entire caller machine is killed; unlike the earlier Firecracker run, the
  external system is the official 24-service application graph rather than a
  purpose-built payment fixture.
- Why the result is not tautological, already settled, or dominated: raw retry
  and stop-after-loss are executed against the same application and failure
  point. The proposed result depends on the concrete generation fence,
  preserved logical identity, query recovery, and absence of another egress
  path, not merely on a checker accepting its own output.
- Paper decision if positive: the system may claim one real cross-domain,
  no-Agent-SDK execution that combines containment, safe continuation, and a
  maintained microservice. It still may not claim arbitrary HTTPS or device
  mediation.
- Paper decision if contradictory, mixed, or inconclusive: a duplicate,
  bypass, or inability to resume would refute the current host-boundary design
  for ordinary Agent tools and force an OS/network interposition redesign
  before any transparent-runtime claim. If the raw path does not duplicate,
  the comparison is non-discriminating and must not support superiority.
- Best alternative experiment and why this one has higher decision value: a
  symbolic planner scaling run would strengthen the algorithmic backend, but
  it would leave the present complete-mediation and community-adoption gap
  untouched. Another MCP or Firecracker-only run is already settled by Steps
  0020--0021.

## Expected And Alternative Outcomes

- Current expected answer: the protected path completes in every repetition
  with one MongoDB reservation and one provider delivery; raw retry completes
  with two matching MongoDB rows; stop-after-loss leaves one row but no
  completed Agent task.
- Strongest competing explanation: receiver behavior or the deterministic
  model, rather than the runtime, prevents duplication. The matched raw path
  therefore uses the same stable request identity, model protocol, VMM failure
  point, adapter, and unmodified application while bypassing History.
- Result that would contradict the expectation: any protected repetition
  duplicates a row, cannot complete after replacement, permits direct provider
  access, or accepts a stale generation; or the raw retry produces only one
  row without receiver-side idempotency.

## Published Precedent And Real Assets

- Closest published protocol: output-commit and RIFL motivate stable result
  identity; Firecracker supplies the microVM boundary; DeathStarBench supplies
  the maintained service graph. Existing repository literature maps these
  foundations and does not treat them as new individually.
- Official system/model/data/benchmark/tool and version:
  - official Claude Code 2.1.233 from its signed release manifest;
  - Firecracker 1.16.1 and Linux 6.1.155 from checksum-pinned artifacts;
  - unmodified DeathStarBench Hotel Reservation 0.3.5 at commit
    `6ecb09706140f8730b5385c08f1386c654c3c526`;
  - the full 24-service Docker Compose graph and its application-owned MongoDB
    reservation collection.
- What is reused: the existing signed Claude fetch, Firecracker cell and
  pidfd-bound failure control, DeathStarBench build/adapter/observer, durable
  Control/History, generation-bound sandbox endpoint, and independent
  evidence-checking patterns.
- Necessary deviations or custom glue: package a minimal shell and HTTP client
  for Claude's built-in Bash tool; expose one fixed guest loopback HTTP port
  through AF_VSOCK; bind a workload-facing HTTP route to the current sandbox
  endpoint; and add a bounded post-commit response delay for deterministic
  failure injection. None changes Claude or DeathStarBench source.

## Comparison

- Proposed system or method: guest loopback HTTP -> generation-bound AF_VSOCK
  relay -> host route -> active sandbox endpoint -> History/Rule gateway ->
  DeathStarBench adapter -> unmodified service graph.
- Main baseline and competing position: **raw retry** sends the same ordinary
  HTTP request through the same VM relay directly to the DeathStarBench adapter
  and retries after source-VMM loss. It represents current retry practice when
  the receiver ignores an idempotency key. It is a matched lower-bound
  comparison, not a claim of superiority over receiver idempotency or manual
  query-before-retry, which remain cited alternatives.
- Why the main baseline needs a matched run instead of citation alone: whether
  this pinned DeathStarBench version duplicates the exact reservation under
  the exact failure and request identity is workload-specific and determines
  whether the proposed comparison is discriminating.
- Controls or ablations, labeled separately:
  - **stop-after-loss / deny-all control:** do not start a replacement call;
    it checks that avoiding retry preserves safety only by losing completion;
  - **bypass control:** the Agent child cannot create AF_VSOCK sockets, each VM
    has no NIC, and only the fixed loopback route is armed;
  - **generation control:** after the source dies, Rule cutover publishes a new
    endpoint; an actively submitted captured old-generation request must be
    rejected with no new adapter delivery or MongoDB row;
  - **receiver-cooperation reference:** receiver-side idempotency is cited, not
    run, because adding it would modify the maintained application and answer a
    different question.
- Conclusion if the main baseline matches or wins: if raw retry does not
  duplicate or the protected path cannot continue, this experiment provides
  no deployability advantage and the runtime direction must be redesigned.
- Information, tuning, and compute fairness: both paths use the same request
  body, stable idempotency key, official Claude binary, deterministic model
  decision, Firecracker resources, application commit oracle, and VMM kill
  condition. Only the host mediation path differs.
- Split or leakage rule: the checker reads retained Agent/VMM/runtime/adapter
  records and Mongo facts but never influences execution. MongoDB is the
  correctness oracle; runtime History and adapter audits cannot substitute for
  it.

## Workloads And Metrics

- Real workload: one-night reservation through the complete DeathStarBench
  Hotel Reservation 0.3.5 service graph, initiated by official Claude's built-in
  Bash tool inside Firecracker.
- Primary metrics:
  - exact count of matching application-owned MongoDB reservation documents
    (the primary external correctness oracle);
  - replacement Agent terminal completion after source-VMM loss;
  - provider deliveries per stable logical request.
- Correctness check or ground truth: exact MongoDB documents joined to the
  stable operation-derived customer identity and full reservation body;
  pidfd/process records prove source destruction and distinct replacement;
  raw Claude stream proves the built-in tool call and final result. Adapter
  deliveries are secondary mechanism evidence. Retained timestamps and events
  must establish commit -> source VMM death -> cutover -> replacement order.
- Repetitions, seeds, and uncertainty: three protected pairs and three raw
  retry pairs with distinct logical identities, plus one stop-after-loss
  control. The model endpoint is deterministic; repeated pairs test the
  asynchronous failure cut rather than statistical model quality.
- Cost estimate: one DeathStarBench graph, thirteen short-lived Firecracker
  VMMs at one vCPU/1 GiB each run serially, and local deterministic model
  traffic. No paid model or cloud service is used.

## Planned Runs

| Run group | Role | Workload | System/method | Repetitions | Decision consequence |
|---|---|---|---|---:|---|
| protected | proposed | DeathStar reservation | History-bound HTTP egress, source kill, generation cutover, replacement retry | 3 | must complete with one row and one delivery |
| raw | main baseline | same | direct HTTP relay, source kill, raw retry | 3 | must complete with two rows and two deliveries |
| stop | control | same | direct HTTP relay, source kill, no replacement | 1 | one row but no completed task |
| bypass | control | all VM runs | no NIC, child AF_VSOCK denial, fixed relay inventory | all | any unmediated path invalidates the protected result |

## Execution

- Authoritative command or workflow: `make runtime-firecracker-deathstar-demo`
  will build/reuse pinned assets, start the official service graph, execute the
  complete matrix, and retain ordinary raw evidence. A separate
  `runtime-firecracker-deathstar-check` command will validate a retained run
  without starting Docker or KVM.
- Real preflight case: one protected source/replacement pair reaches a real
  MongoDB commit, proves that no response byte reached the source guest, then
  kills and reaps the exact source VMM with SIGKILL. The real VMM kill, not an
  adapter-only dropped response, creates the uncertainty. The runtime then
  cuts over the sandbox generation and completes in the clean VM.
- Full completion rule: every planned repetition reaches its declared terminal
  state; all source VMMs are absent; proposed/raw/stop Mongo multiplicities are
  respectively 1/2/1; protected replacement tasks finish; raw replacement
  tasks finish; stop does not; no proposed request bypasses the bound route;
  the independent checker and repository regression pass.
- Raw-result path:
  `docs/tmp/bootstrap/step-0022-20260817T025925Z/experiment-firecracker-deathstar-egress/raw/`.
- Checkpoint or recovery approach: the service graph remains live across the
  serial matrix; every repetition uses a distinct logical identity. Failed
  preflights are retained outside the final raw directory and never counted as
  a completed run.

## Interpretation

- Positive result: the generation-bound host boundary is sufficient for this
  ordinary built-in HTTP action and preserved useful continuation across full
  VMM loss, while current raw retry duplicates the unmodified receiver.
- Negative or contradictory result: retain it in the repository and redesign
  the egress or generation protocol; do not weaken the hypothesis or place a
  negative result in the paper.
- Mixed or inconclusive result: any race-dependent duplicate, stale-generation
  delivery, missing application truth, or incomplete matrix makes the run
  incomplete or invalid rather than a partial success.
- Target paper figure or table: one failure timeline and a three-row table
  comparing Mongo multiplicity, provider deliveries, task completion, Agent
  modification, and direct-egress availability.

## Reproducibility Notes

- Software and data versions are pinned above and will be recorded with image,
  binary, payload, kernel, and source-tree hashes.
- Each repetition uses a unique declared identity but no random workload
  choice. VM/session IDs remain random and are retained as evidence.
- The deterministic local model endpoint controls only Claude's tool choice;
  it is not the safety mechanism or result oracle.
- This experiment defines transparent as no Claude or DeathStarBench source
  modification; an operator still registers the route and identity-key rule.
  It covers registered plaintext HTTP with an application-owned stable key. It
  does not claim transparent HTTPS inspection, arbitrary socket
  protocols, device DMA, semantic identity inference, remote attestation,
  fleet scheduling, or production performance.
