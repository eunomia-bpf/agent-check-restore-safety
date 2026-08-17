# Experiment Plan: RQ4 stable operation identity across Agent replacement

## Research Question
- RQ exactly as written in the paper: The paper has no numbered RQs. Its deployment claim is that the runtime “preserves safety across repeated edits and restarts”; the canonical evaluation asks, “RQ4: Is there a deployable algorithmic boundary?”
- Specific uncertainty tested here: Can the host runtime recognize a completed or in-flight external operation after a replacement Agent changes both its MCP request identity and the order in which it asks for operations?
- Why the answer matters: The current adapter is transparent only while a replacement repeats the same call position. Real model, runtime, and scheduling changes do not preserve that position.

## Paper-Value Admission
- Planned role: supporting systems evidence for RQ4 and a required correctness repair for transparent deployment.
- Largest credible paper story this experiment could unlock: One host-held operation boundary can preserve external-operation continuity across process, VM, and model-scheduling changes without modifying the Agent runtime.
- Strongest reviewer reject argument or load-bearing uncertainty addressed: Existing continuity results may be artifacts of deterministic replay because MCP JSON-RPC order, rather than the application’s existing operation identifier, currently selects saved results.
- Independent evidence added beyond existing runs and published results: A matched implementation comparison under changed request identities and reordered calls, followed by a real official Codex process-replacement run.
- Why the result is not tautological, already settled, or dominated: The present implementation explicitly keys the journal by RPC ID; all retained real-Agent recovery runs preserve call order.
- Paper decision if positive: Retain the transparent host boundary and state that replacement need not reproduce transport identity or call order.
- Paper decision if contradictory, mixed, or inconclusive: Keep the current fail-closed boundary, document deterministic replay as a deployment requirement, and do not claim schedule-independent continuity.
- Best alternative experiment and why this one has higher decision value: Adding a Firecracker jailer would strengthen containment but would not test whether recovered work is recognized correctly.

## Expected And Alternative Outcomes
- Current expected answer: An operator-declared projection of already-required tool arguments can give the same external operation one stable host key; the full canonical request can independently reject changed work.
- Strongest competing explanation: Agent-native call IDs already remain stable enough that the additional mapping has no practical effect.
- Result that would contradict the expectation: Official Codex cannot complete after call reordering, or the projection permits a changed full request to reuse an earlier result.

## Published Precedent And Real Assets
- Closest published protocol: The repository’s existing write-ahead Operation journal and recovery query protocol; no external protocol is substituted.
- Official system/model/data/benchmark/tool and version: Official native Codex 0.147.0; existing deterministic Responses fixture; real Control, History, Unix-socket MCP host/relay, and non-idempotent local provider.
- What is reused: The pinned binaries, current process-replacement workload, strict journal, provider, evidence checker, and full Firecracker/Claude regression.
- Necessary deviations or custom glue: Tool configuration declares which required primitive arguments identify one operation; journal schema 2 records that key and stores an RPC-ID-neutral response.

## Comparison
- Proposed system or method: Stable operation identity derived from operator-declared business arguments, with full-request conflict checking.
- Main baselines and the competing position each represents: Current schema 1 journal keyed by JSON-RPC ID represents positional deterministic replay.
- Why each main baseline needs a matched run instead of citation alone: This is a component-level implementation claim about the repository’s own recovery behavior.
- Controls or ablations, labeled separately: Same stable identity with changed non-identity arguments must reject without provider dispatch; a different operation requested first must remain independent; legacy journals must still replay exactly.
- Conclusion if each main baseline matches or wins: If positional replay handles changed IDs and order equally, schema 2 adds no deployment value and should not ship.
- Information, tuning, and compute fairness: Both methods receive the same tool schema and canonical request; only schema 2 receives the operator’s declared identity projection. No model tuning is used.
- Split or leakage rule when relevant: Not applicable; the deterministic model endpoint drives a fixed systems trace and is not evaluated for intelligence.

## Workloads And Metrics
- Real workloads or tasks: Two official Codex App Server processes sharing one host runtime; source commits A, replacement requests B and then reuses A with new model and MCP identities.
- Primary metrics: Provider deliveries and commits per distinct `effect_id`; saved-result reuse after changed request identity; changed-request conflicts admitted; successful completion of both Codex calls.
- Correctness check or ground truth: Exactly one provider commit for A and B, two History Operations, no dispatch for replayed A, schema-2 hash chain valid, and independent checker acceptance.
- Repetitions, seeds, and uncertainty: One deterministic real-process run after exhaustive Go lifecycle tests. This is functional evidence, not a performance estimate.
- Cost estimate when material: Local CPU only; no paid model or network service.

## Planned Runs
| Run group | Role | Workload | System/method | Repetitions | Decision consequence |
|---|---|---|---|---:|---|
| unit lifecycle | proposed + controls | completed, pending, reordered, conflict, reopen | schema 2 journal/server | exhaustive cases | blocks implementation on any duplicate or misbinding |
| compatibility | control | retained positional replay | schema 1 journal/server | exhaustive cases | blocks release if old evidence no longer verifies |
| real process | proposed | Codex source A; replacement B then A with new call IDs | official Codex + host runtime | 1 | tests transparent schedule-independent reuse |
| full regression | control | all retained runtime paths, including Firecracker Claude | repository verification | 1 | blocks release on cross-backend regression |

## Execution
- Authoritative command or workflow: `make runtime-codex-mcp-demo` for the real run and `make runtime-verify` for the full regression.
- Real preflight case: Build and exercise the schema-2 MCP host against the actual Control/provider path before launching Codex.
- Full completion rule: All lifecycle tests pass; real Codex produces exactly two provider commits for A/B under reordered replacement; evidence checker and full runtime verification pass.
- Raw-result path: `docs/tmp/bootstrap/step-0021-20260817T022256Z/experiment-stable-operation-identity/raw/`.
- Checkpoint or recovery approach: Preserve final raw evidence only after validation; rerun into a fresh directory after any implementation repair.

## Interpretation
- Positive result: The external-operation record, not VM state, model call ID, MCP ID, or call position, is the continuity anchor.
- Negative or contradictory result: Restrict the transparent claim to deterministic replay and retain the failed evidence for diagnosis.
- Mixed or inconclusive result: Separate transport-ID independence from order independence and claim only the property directly demonstrated.
- Target paper figure or table: None in this step; paper text remains unchanged until the broader RQ4 evidence is reviewed together.

## Reproducibility Notes
- Software and data versions: Repository `a6a38b1`; official Codex 0.147.0; existing pinned provider/runtime artifacts.
- Config and seed notes: Fixed effects A/B; no random seed; fresh private evidence directory.
- Known deviations: Local deterministic model endpoint; one correctness run; no latency claim.
