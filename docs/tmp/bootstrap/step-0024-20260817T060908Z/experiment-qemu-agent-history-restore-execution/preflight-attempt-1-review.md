# Step 0024 preflight attempt 1 review

## Command

`sg kvm -c 'make runtime-qemu-agent-restore-preflight QEMU_AGENT_RESTORE_PREFLIGHT_EVIDENCE=docs/tmp/bootstrap/step-0024-20260817T060908Z/experiment-qemu-agent-history-restore-execution/preflight-attempt-1'`

## Outcome

Infrastructure failure before any Agent or application request; no scientific
result.

- The full Ubuntu preparation VM completed, sealed snapshot `before_agent`,
  quit, and was reaped.
- The first H1 source runner failed during its immediate live process-identity
  capture with `source-vm-runner did not start as an independently killable
  process group`.
- `source-vm` remained empty, the runner emitted no event or stderr byte, the
  DeathStar audit is empty, and no Agent/application request occurred.
- Cleanup found one completed preparation runner and QEMU, no residual before
  cleanup, no terminated PID, and no residual after cleanup.

## Cause and repair

The exact failing assertion combined three conditions but did not retain which
condition failed. The preparation runner had passed the same PGID/SID checks;
the source runner failed immediately after `Popen`, where `/proc/PID/cmdline`
was read once. Linux may expose an empty command during this launch transition,
and the one-shot read could therefore kill an otherwise valid new session.

The repair retries only an empty `/proc/PID/cmdline` for at most one second,
fails immediately if the child actually exits, and reports PID, PGID, SID, and
command length for any remaining mismatch. A mutation/unit test forces one
empty read followed by a complete command and verifies the bounded retry.

## Disposition

Attempt 1 is retained unchanged and is not counted as H1, H0, native, or a
partial success. Attempt 2 may run only after static tests and independent
review of this narrow repair.

## Independent attempt-2 admission

Approved. The reviewer treated transient empty `cmdline` as the most likely,
not proven, cause because the old assertion combined three conditions. The
repair is nevertheless admissible: it retries only an empty command, remains
bounded to one second, still rejects child exit and PGID/SID mismatch, and now
distinguishes those cases. The reviewer ran no experiment and made no file
change.
