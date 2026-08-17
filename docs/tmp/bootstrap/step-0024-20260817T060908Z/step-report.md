# Step 0024 report

## Experiment gate

**Status:** closed incomplete at 2026-08-17T08:03:26Z.

The selected RQ was RQ4, “Is there a deployable algorithmic boundary?” The
decisive question was whether one host-owned History and exact edit decision
could be the sole authority for resuming an unchanged official Agent from a
complete VM snapshot, with the same checkpoint and target receiving opposite
answers under different external histories.

The reviewed plan and implementation are in
`experiment-qemu-agent-history-restore-execution/`. Three permitted real
preflights contacted QEMU/KVM and the complete Ubuntu path. Attempts 1 and 2
failed respectively at runner identity capture and before an observable Agent
request. Their repairs were independently admitted. Attempt 3 proved the model
guest forward reachable but retained zero Messages requests after unchanged
official Claude was launched. All three attempts stopped before any scientific
comparison and retained clean process/application cleanup evidence.

No preflight passed, so the H1/H0/native matrix, admission seal, evidence
checker, and result review did not run. This step adds no RQ evidence and makes
no paper change. The complete failure record is:

- `preflight-attempt-1-review.md` and `preflight-attempt-1/`;
- `preflight-attempt-2-review.md` and `preflight-attempt-2/`; and
- `preflight-attempt-3-review.md` and `preflight-attempt-3/`.

The implementation remains aligned with the user instruction: it is a real
host-owned resume guard over complete QEMU, official Claude, live authenticated
Control state, exact History/Certificate, and DeathStarBench/Mongo rather than
a toy simulation. The failed launch path does not justify narrowing the
system objective or changing the scientific contract.

## Write gate

Skipped. There is no accepted result, and no file under `docs/paper/` changed.

## Review and route

The three-attempt preflight limit closes this experiment. The next
highest-value branch is not a fourth QEMU retry. It is to make the same exact
History/Certificate decision the sole replacement authority in the existing
official-Claude Firecracker plus DeathStarBench vertical, whose real model,
Bash, VMM-loss, Mongo, and clean-replacement paths already passed. QEMU remains
a supported/debug backend; Firecracker becomes the production-oriented
backend. This preserves the larger system thesis that VM state is disposable
while external-operation truth and future admission live on the host.

The current user instructions were reread at gate entry. The step changed no
term, RQ, claim, scope, or paper narrative, and introduced no new public term.
