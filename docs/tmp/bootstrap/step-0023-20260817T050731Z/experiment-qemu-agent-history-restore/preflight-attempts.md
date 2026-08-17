# Real Preflight Attempts

## Attempt 1

- Command: `sg kvm -c 'make runtime-qemu-agent-restore-preflight'`
- Result: failed before VM boot.
- Cause: the QMP Unix socket inherited the long retained-evidence path and
  exceeded Linux's 108-byte Unix-socket address limit.
- Scientific outcome: none; no Agent or application request executed.
- Repair: QMP now lives in a fresh private short `/tmp/safe-change-qmp-*`
  directory owned only by the VM supervisor. The synchronized QMP protocol
  remains in the retained evidence directory, and the supervisor removes the
  private socket after QEMU is reaped.

## Attempt 2

- Command: `sg kvm -c 'make runtime-qemu-agent-restore-preflight QEMU_AGENT_RESTORE_PREFLIGHT_EVIDENCE=docs/tmp/bootstrap/step-0023-20260817T050731Z/experiment-qemu-agent-history-restore/preflight-attempt-2'`
- Result: failed after the 24-service application became healthy and the base
  VM checkpoint was sealed, but before the first VM request.
- Cause: the Control-owned sandbox socket, distinct from QMP, still inherited
  the long retained-evidence path and independently exceeded Linux's
  108-byte Unix-socket address limit.
- Scientific outcome: none; no Agent or application request executed.
- Repair: live sandbox sockets now use per-lane directories below one fresh,
  mode-0700 short `/tmp/qemu-agent-restore-*` transport root. Durable History,
  manifests, process and endpoint identity, and all protocol evidence remain
  under the retained evidence root; cleanup occurs only after all owning
  processes are reaped.

## Attempt 3

- Command: `sg kvm -c 'make runtime-qemu-agent-restore-preflight QEMU_AGENT_RESTORE_PREFLIGHT_EVIDENCE=docs/tmp/bootstrap/step-0023-20260817T050731Z/experiment-qemu-agent-history-restore/preflight-attempt-3'`
- Result: failed after the complete qcow2 was sealed, Control cutover and the
  sandbox endpoint succeeded, and the H1 source QEMU loaded the named snapshot;
  it failed before the first Agent or application request.
- Cause: QEMU 8.2 reports an initially halted `-S` VM as
  `status=prelaunch,running=false`. The supervisor incorrectly required the
  literal status `paused`, which QEMU reserves for a later explicit `stop`.
- Scientific outcome: none; QMP killed the VM before the first `cont`, so no
  Agent or application request executed.
- Repair: the supervisor now requires exactly
  `status=prelaunch,running=false` after `-S -loadvm before_agent`, calls this
  state `snapshot-loaded-halted`, and continues to require
  `status=paused,running=false` after an explicit `stop`. The independent
  checker validates both exact state transitions.

## Disposition

All three admitted real preflight attempts ended before any Agent/application
request. The independent amendment review found the third repair causally
valid but ruled that focused validation cannot substitute for a successful
end-to-end preflight. Step 0023 therefore ends incomplete at the preflight
gate. It has no accepted full run and makes no scientific claim. A later,
separately admitted execution may inherit the repaired implementation only if
it discloses these failures and performs a new reviewed preflight; it may not
present that execution as a Step 0023 full run.
