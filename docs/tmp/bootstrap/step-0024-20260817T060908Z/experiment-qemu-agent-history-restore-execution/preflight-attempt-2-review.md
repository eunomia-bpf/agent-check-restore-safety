# Step 0024 preflight attempt 2 review

## Command

`sg kvm -c 'make runtime-qemu-agent-restore-preflight QEMU_AGENT_RESTORE_PREFLIGHT_EVIDENCE=docs/tmp/bootstrap/step-0024-20260817T060908Z/experiment-qemu-agent-history-restore-execution/preflight-attempt-2'`

## Outcome

Infrastructure failure after official Claude started but before any application
request; no scientific result.

- The preparation VM booted complete Ubuntu, sealed snapshot `before_agent`,
  quit, and was reaped.
- The H1 source VM loaded that snapshot in exact QMP state
  `prelaunch,running=false`, received `cont`, and emitted the session-bound
  official-Claude start marker.
- During the following 30 seconds, DeathStarBench received zero deliveries and
  the egress relay accepted zero connections. The source VM was terminated by
  the driver's failure cleanup.
- The source and effect proxies remained healthy. Cleanup inspected both
  preparation and H1 source runner/QEMU pairs, terminated no residual process,
  and found no residual afterward. The run did not time out.

## Cause and repair

The retained evidence cannot distinguish whether Claude reached the local
Messages endpoint: the driver wrote `anthropic-requests.json` only after a
complete matrix, and stderr was not retained. The immediate 30-second
application wait therefore collapsed model startup, model transport, Bash tool
selection, and application delivery into one error.

Source inspection found one concrete discrepancy from the already successful
Firecracker Claude path. The QEMU guest created `/run/claude-workspace` but did
not enter it, so Claude inherited cloud-init's working directory. The repair is
bounded and does not change the experiment's hypothesis, target, oracle, or
application action:

1. enter the private empty workspace before launching unchanged Claude;
2. probe `/health` through the same QEMU model `guestfwd` before declaring
   Claude started, without consuming a model request;
3. wait explicitly for the next Messages request before starting the existing
   application-delivery timeout; and
4. atomically retain model requests, fixture failure, precise progress error,
   and driver stderr on both success and failure.

## Disposition

Attempt 2 is retained unchanged and is not H1, H0, native, or partial success.
Attempt 3 is the final permitted real preflight. It may run only after the
repair passes targeted and full static checks and an independent reviewer
confirms that the changes are diagnostic/operational rather than a changed
experiment.

## Independent attempt-3 admission

Approved. The reviewer independently confirmed that attempt 2 stopped before
any model output, Bash action, History operation, relay connection, or
DeathStarBench delivery and therefore contains no scientific result. The
reviewer also confirmed that the repair preserves the same official Claude,
prompt, Bash action, seven-request total, H1/H0/native conditions, and final
oracles. `/health` does not consume a Messages request, and the workspace fix
only aligns QEMU with the already verified private-working-directory launch.
The exact attempt-2 cause remains unproved; attempt 3 is admitted because it
removes that concrete discrepancy and makes every remaining startup boundary
distinguishable. The reviewer ran no KVM, Docker, build, or experiment command
and changed no file.
