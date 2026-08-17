# Step 0022: ordinary Agent HTTP across Firecracker and DeathStarBench

Status: completed, 2026-08-17T04:54:20Z. Phase: BUILD_AND_EVALUATE. Gate path:
EXPERIMENT, light documentation update, REVIEW.

## EXPERIMENT

The admitted question was whether the same host Operation boundary could sit
below an unchanged Agent's built-in Bash/HTTP path, survive complete sandbox
loss, and recover against a maintained unmodified application. This ranked
above adding Firecracker `jailer` or another MCP-only workload because built-in
tool bypass and purpose-built receivers were the largest remaining objections
to the system direction.

The frozen and independently approved plan is
`experiment-firecracker-deathstar-egress/plan.md`. The implementation added:

- an exact registered HTTP route backed by a generation-bound sandbox socket;
- a no-NIC Firecracker Claude profile with real Bash and fixed local egress;
- source-socket generation pinning and stale-generation rejection;
- a post-commit application failure window;
- a complete DeathStarBench 0.3.5 launcher and three-condition driver; and
- an independent evidence checker over History, Mongo facts, application,
  Firecracker, and Claude records.

The first independent result review rejected a full run because Mongo row
counts were not independently retained. The observer was repaired to export
all bounded matching facts and their hashes; a new preflight and new full run
were then executed. A fresh reviewer approved only the repaired result. The
complete audit is in
`experiment-firecracker-deathstar-egress/result-review.md`.

Accepted direct evidence is under
`experiment-firecracker-deathstar-egress/raw/`. The independent checker passed
with three protected runs at one row, three raw retries at two rows, and one
stop control at one row without task completion. Thirteen distinct Firecracker
VMs and 19 retained Mongo queries support the matrix.

## Verification

- repaired real-KVM preflight: pass;
- repaired three-repetition real-KVM matrix: pass;
- independent retained-evidence checker: pass;
- `go test ./...`: pass;
- `go vet ./...`: pass;
- race tests for all changed runtime packages and commands: pass;
- 175 Python tests: pass; and
- `git diff --check`: pass.

## Documentation update

No file under `docs/paper/` changed. The light update records established
implementation facts and reproduction commands in `docs/evaluation.md`,
`docs/system-contract.md`, `docs/implementation.md`, `docs/idea-story.md`, and
`docs/firecracker-deathstar-runtime.md`.

## REVIEW and routing

The result supports RQ4 and the larger system direction: the sandbox is a
replaceable failure boundary, while correctness lives in host History and
application facts. It also removes two earlier evidence limitations for one
bounded action: the Agent uses an ordinary built-in tool, and the receiver is a
maintained full microservice application rather than a fixture.

It does not establish transparent arbitrary egress, production deployment,
performance, unqueryable actions, or superiority over receiver-side
idempotency. The next route is a normal agent-runtime launcher that registers
several common service protocols and supports process, container, Firecracker,
and full-VM backends without changing the correctness core.
