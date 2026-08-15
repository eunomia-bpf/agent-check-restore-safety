# Experiment Plan: RQ4 — Real Program Replacement After External Operations

## Research Question

- RQ exactly as written in the repository: **RQ4: Is there a deployable algorithmic boundary?**
- Specific uncertainty tested here: Can the runtime replace a live, long-running order program after an external payment attempt, without per-instance migration code, by using History to distinguish two executions that have the same Restate-visible workflow position but require opposite edit decisions?
- Why the answer matters: A positive answer is the first real-system evidence that the project is more than an HTTP retry wrapper or an offline policy checker. It would show that History can decide and enforce a program change that ordinary journal compatibility cannot decide.

## Paper-Value Admission

- Planned role: **decisive**.
- Largest credible paper story this experiment could unlock: A running program with real external effects can be replaced safely without retaining the old program or writing a state-by-state migration; safe executions continue and unsafe executions receive a History-bound impossibility Certificate.
- Strongest reviewer reject argument or load-bearing uncertainty addressed: The current runtime may only be repackaging stable idempotency keys, external querying, and old-version draining. It has not yet replaced a maintained long-running workflow at a point where replay compatibility lacks the fact needed to choose safely.
- Independent evidence added beyond existing runs and published results: The workload is the official Restate `food-ordering` application, with real Restate invocations, immutable deployments, durable sleep/promise state, and the official Admin/CLI lifecycle. Existing DeathStar evidence has no durable-workflow journal or live invocation replacement.
- Why the result is not tautological, already settled, or dominated: H0 and H1 hold the Restate invocation at the same unresolved payment step and use the same target v2. Only the external fact differs. Native Restate and Temporal are run through their official version mechanisms; the proposed system must distinguish H0 from H1 using independently checked History and effect state.
- Paper decision if positive: Promote “safe replacement after external operations” from a direction to the first system claim, while keeping the result scoped to registered HTTP Operations and the tested workflow.
- Paper decision if contradictory: If native Restate or Temporal makes the same distinction automatically, or if the proposed runtime needs target-specific state migration, demote the result to adapter engineering and redesign the core claim.
- Paper decision if mixed or inconclusive: Retain only the cells whose actual invocation, external fact, and Rule decision are independently established. Do not infer the missing comparison.
- Best alternative experiment and why this one has higher decision value: Online Boutique would add another microservice graph but no maintained long-running journal. Scaling the existing compiler would improve engineering without deciding whether the abstraction can replace a real running program.

## Expected And Alternative Outcomes

- Current expected answer: For the same v2 that removes the old payment step, H1 (payment durably committed, response lost) can be queried, recorded as succeeded, and continued under v2; H0 (no durable payment) must be rejected because the target has no remaining executable way to satisfy the payment Requirement. The target catalog retains a disabled `charge-v1` entry only so old History can be interpreted; it has no target and is neither retry-safe nor queryable. The old Operation's query contract remains frozen in History.
- Strongest competing explanation: Stable payment tokens plus Restate/Temporal versioning already provide the same useful behavior by retrying, pinning, draining, or developer-written version branches; the proposed runtime adds no automatic decision. A second possibility is more damaging: because Restate records a `ctx.run` result only after the closure returns, both H0 and H1 may look compatible with v2 and Restate may skip payment in both, admitting H0 without the missing external fact.
- Result that would contradict the expectation: Either baseline safely moves both H0 and H1 to the unmodified target v2 without a version branch, old worker, or migration, or the proposed runtime cannot complete H1 and reject H0 from the frozen evidence.

## Published Precedent And Real Assets

- Closest published/official protocol: Restate service versioning and invocation pause/resume; Temporal Worker Deployments with Pinned and AutoUpgrade workflows.
- Official system and version: Restate examples tag `v1.7.7`, commit `2d429daae784d20982691fb31431702b4ad30a6b`; Restate server `1.7.3` at `sha256:1856961b7a16d1b00131e5704231b79e0334703df074a31867ea8ce2110d5cfa`; Restate TypeScript SDK `1.16.6`; Temporal samples-go commit `dd33bba4f481623958da5a7119bdf49eb72a4c87`; Temporal CLI `1.8.2` containing server `1.31.2`.
- What is reused: The complete official `typescript/end-to-end-applications/food-ordering` application, its order workflow and durable wait, Restate registration and invocation commands, and the official Temporal Worker Deployment mechanism.
- Necessary deviations or custom glue: Replace the official payment stub with one durable, intentionally non-idempotent HTTP effect service; route the payment call through the project Operation API; add immutable v1/v2 order endpoints; add deterministic pre-commit and post-commit response holds; add an independent result checker. The order workflow's business stages remain the official stages.

## Comparison

- Proposed system: The project runtime stores the exact external request in History, resolves unresolved Operations from the authoritative effect service, compiles the target Requirement, atomically activates its Rule, fences v1 protected calls, and starts the logical order continuation under v2.
- Main baseline 1: Native Restate immutable deployments plus official pause/resume and old-version draining. This represents journal compatibility and production version pinning. A matched run is necessary because the claim concerns one actual unresolved `ctx.run` and a target deployment on this official application.
- Main baseline 2: Temporal Worker Deployments with Pinned and AutoUpgrade executions, including an explicit version branch when needed. This represents replay-safe code versioning and the strongest common developer-managed alternative. A matched run is necessary to separate automatic History-based replacement from manual compatibility code on the same external fact.
- Controls or ablations: compatible v2 edit; unsafe v2 edit; proposed runtime with external query disabled; direct retry against the non-idempotent provider using the same stable token; old-version drain.
- Conclusion if a baseline matches or wins: If an unmodified target v2 automatically distinguishes H0/H1, the proposed mechanism is not a new systems capability. If a manual version branch matches, the result is an automation and retained-code comparison, not a safety superiority claim.
- Information, tuning, and compute fairness: Every system receives the same order body, stable payment token, intentionally non-idempotent effect service, fault moment, target v2 semantics, business Results, Capacities, and resource budget. The token is an identity for observation, not a provider-side deduplication mechanism. The v2 operation catalog changes because the program changes, but it is identical between H0 and H1. Only the proposed system receives its own History; a baseline may use every fact its official runtime records. A manually supplied baseline branch is reported separately and is never described as automatic.

## Workloads And Metrics

- Real workload: One official Restate food order spanning payment, durable wait, restaurant preparation, delivery matching, and completion. The matched Temporal port preserves the same business stages and HTTP effect.
- Primary outcomes: exact accept/refuse decision for H0 and H1; whether every accepted order reaches its required terminal state; external deliveries; durable payment commits; whether the same POST would create another charge; whether any v1 protected call occurs after v2 activation; and whether old code is still required.
- Correctness check or ground truth: An independent checker joins the effect service's fsynced records, Restate/Temporal invocation state, process/container identity, the hash-linked History, Requirement, Rule, Certificate, and final business state. Runtime output is not its own oracle.
- Repetitions and uncertainty: Five clean deterministic repetitions per matrix cell. Report every run; no statistical inference is used for the exact decision. Latency is secondary and summarized only after correctness passes.
- Cost estimate: The Restate Compose application requires Kafka, Jaeger, Web UI, runtime, and application services; reserve 4 CPUs, 8 GiB memory, and 10 GiB temporary disk. Temporal runs after the Restate matrix to avoid resource contention.

## Planned Runs

| Run group | Role | Workload | System/method | Repetitions | Decision consequence |
|---|---|---|---|---:|---|
| compatible | control | payment completed; future closure changes only | proposed, native Restate, Temporal AutoUpgrade | 5 each | All must continue; failure invalidates fairness or compatibility. |
| history-aware H1 | main | payment committed; closure has not returned; target v2 removes payment | proposed, native Restate, Temporal Pinned/AutoUpgrade/manual branch | 5 each | Proposed must continue without v1 or per-instance migration. Baseline behavior establishes whether this capability is distinct. |
| history-aware H0 | main | no payment commit; same closure and workflow location; same target v2 | proposed, native Restate, Temporal Pinned/AutoUpgrade/manual branch | 5 each | Proposed must refuse; any completion without payment is a safety failure. |
| unsafe | control | committed facts make one target Requirement impossible | all systems | 5 each | Every system must refuse, retain a safe old execution, or require explicit changed Requirements. |
| no-query | ablation | H1 with authoritative query removed | proposed | 5 | Must fail closed; acceptance would invalidate the claimed evidence boundary. |
| old-drain | current practice | H0 and H1 retained on v1 | Restate and Temporal Pinned | 5 each | Establishes the retained-code availability and worker-time cost, not an unsafe strawman. |

## Execution

- Selected systems technique: one mixed-version upgrade test combined with one deterministic unknown-result crash-recovery cut and an authoritative durable-state comparison. Scale, load, and latency sweeps are excluded because they do not answer this uncertainty.
- Authoritative workflow: Pin and build the official repository, start its documented Compose graph with the Restate image digest fixed, register v1 and v2 through the official Admin API/CLI, submit a real order through Restate ingress, and use official invocation pause/resume commands. The Temporal comparison uses the pinned official Worker Deployment path.
- Real preflight case: One H1 order must enter the official workflow, durably commit one payment, keep the HTTP closure from returning, hard-stop v1, remain unresolved in Restate, then be safely completed by the proposed v2 with v1 removed. A separate direct-retry control must show that the same provider request would create a second charge.
- Full completion rule: Every planned cell reaches an explicit terminal verdict; all official services and actual invocation IDs are retained; H0/H1 equality in the Restate journal and workflow state is checked before either result is interpreted; the payment closure has not returned in either history; external effect truth differs; every accepted order satisfies its Requirement; no run duplicates a payment commit; the independent checker passes all positive evidence and rejects every mutation. If the two Restate journals already differ, the decisive comparison is invalid and must be redesigned.
- Raw-result path: `docs/tmp/bootstrap/step-0016-20260815T153407Z/experiment-restate-food-ordering/raw/`.
- Checkpoint or recovery approach: Each repetition uses a new Compose project and data directory. Failed attempts are retained with the exact command and reason. Runtime and effect data are copied before teardown; containers are then removed explicitly.

## Interpretation

- Positive result: The same target v2 and same Restate-visible unresolved step receive opposite correct answers from H0 and H1; H1 finishes under v2 after v1 is removed, H0 receives an impossibility Certificate, compatible changes still work, and unsafe changes never execute.
- Negative or contradictory result: Duplicate payment, a v1 call after activation, H0 completion, H1 dependence on v1 or a per-state migration branch, baseline automatic equivalence, or checker disagreement invalidates the central claim.
- Mixed or inconclusive result: A baseline configuration failure, missing official invocation evidence, or observer ambiguity makes only that comparison inconclusive. It is not counted as a proposed-system win.
- Target paper figure or table: One decision matrix showing H0/H1, target v2, available evidence, automatic decision, old-code requirement, deliveries, commits, and terminal state.

## Reproducibility Notes

- Software and data versions: All revisions and image digests above are fixed; generated source archives and dependency lock files are hashed in raw evidence.
- Config and seed notes: Operation identities derive from the Restate-stable payment token and logical order ID. Faults are deterministic, not random. Repetitions use unique project and order IDs.
- Known deviations: The official payment client is a stub and must be replaced to create a real irreversible boundary. The effect service is local and authoritative for this experiment; this run does not establish behavior for a dishonest, unreachable, or non-queryable provider. The Temporal application is a matched port, not an official food-ordering sample.
