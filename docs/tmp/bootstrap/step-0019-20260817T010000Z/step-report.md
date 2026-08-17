# Step 0019: one host boundary across real Claude and Codex

Date: 2026-08-17 UTC

## Recovery and alignment

This step resumed the newest incomplete runtime node after rereading
`docs/user-instruction.md`, the Step 0018 report, and the current implementation
and evaluation frontiers. It implements the user's request for a real system
spanning Claude, Codex, complete virtual machines, and microservices while
keeping community adoption transparent. It does not change the paper or the
frozen theoretical contract.

The selected uncertainty was whether the provider-independent MCP boundary was
actually portable to an unmodified second Agent runtime. Existing Codex,
Firecracker/KVM, DeathStarBench, Restate, and Temporal evidence could not answer
that vendor-interface question.

## EXPERIMENT gate

Plan:
`experiment-claude-process-continuity/plan.md`.
Plan audit:
`experiment-claude-process-continuity/plan-review.md`.
Result review:
`experiment-claude-process-continuity/result-review.md`.

The official Claude Code 2.1.233 binary ran twice against the same long-lived
host MCP process. The first process called A; the non-idempotent provider
committed it and held the response; the supervisor killed the complete Claude
process group; the host then completed A; a clean second Claude process replayed
A, committed B, returned `DONE`, and exited zero.

The retained final result is at
`experiment-claude-process-continuity/raw/`. A separate checker returned
`valid=true` after reconstructing two processes, two relay children, four model
requests, four MCP records, seven History events, two Operations, and exactly
two provider commits. The source exit is `-9`; the replacement exit is `0`;
no runtime credential remains.

Two failed attempts are retained. The first found that a Unix socket path was
incorrectly coupled to a long evidence directory. The second found an
unremoved control lock in the new temporary transport root. The final design
keeps ephemeral transport names short and deletes the validated lock and socket
directories after the trusted services stop.

## WRITE gate

Skipped for the paper. This is supporting implementation evidence and does not
change a result slot or the scientific contract. The implementation,
evaluation, runtime README, and dedicated reproduction document were updated;
no file under `docs/paper/` changed.

## REVIEW gate

Direction: the step preserves the larger system direction. Firecracker remains
a disposable execution mechanism; durable external Operations remain in the
host boundary. Claude and Codex now use the same untrusted-relay/host-journal
contract, while the already retained Firecracker, KVM, microservice, Restate,
Temporal, and DeathStar paths continue to pass.

Efficiency: the real preflight found the Claude protocol compatible on its
first execution. The only reruns repaired deployability and cleanup defects,
and both failures are retained. No new control schema, paper terminology, or
empty architecture scaffolding was added.

Maintenance: the stable public entry points are now
`runtime-claude-fetch`, `runtime-claude-mcp-demo`, and
`runtime-claude-mcp-check`. No new repository skill or `AGENTS.md` rule is
justified by this one vendor integration.

## Verification

- Anthropic release key fingerprint and manifest signature: valid.
- `make runtime-claude-mcp-check .../raw`: valid.
- `make runtime-verify`: Go build, Go race tests, Go vet, 112 Python tests,
  retained Codex isolation, retained KVM integrated run, and retained
  DeathStarBench run all passed.
- `git diff --check`: passed.

## Next action

Place this exact Claude command and stdio relay contract inside the existing
Firecracker guest payload. Destroy the source VMM at the same held-provider
cut, boot or restore an independent VMM, and require the same host journal and
independent checker to prove that A is not delivered twice before B completes.
