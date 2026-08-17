# Step 0020: official Claude across complete Firecracker loss

Date: 2026-08-17 UTC

## Outcome

The runtime now runs official Claude Code 2.1.233 as an unprivileged process in
a real networkless Firecracker microVM, kills the complete source VMM after an
external provider commit but before its result returns, and completes the same
work through a clean replacement VM. History, the MCP journal, Operation
identity, provider state, and model endpoint remain outside both VMs.

The final run produced two different VMM identities, two Operations, two
provider deliveries, exactly two provider commits, and `DONE`. It used no
memory snapshot. An independent checker passed the retained and relocated raw
evidence and rejected a tampered copy.

## System changes

- Added a fixed official-Claude Firecracker guest, host cell runner, and
  immutable SquashFS payload builder.
- Added separate generation-bound AF_VSOCK relays for the model and MCP paths.
- Added a whole-VMM-loss demo and standard-library-only evidence checker.
- Hardened guest configuration and result parsing against missing, unknown,
  duplicate, trailing, and oversized JSON.
- Changed the Firecracker result gate to treat newline as the protocol frame
  boundary because guest `SHUT_WR` is not reliably forwarded as host Unix EOF;
  already coalesced trailing bytes remain rejected.
- Added public Make targets and reproduction documentation.

No file under `docs/paper/` changed.

## Research gate

This is supporting systems evidence for RQ4, not a new paper claim. The plan,
audit, result review, checker summary, negative test, and complete 204 KiB raw
run are in `experiment-firecracker-claude-continuity/`.

## Verification

- Real KVM final run: PASS.
- Independent final-evidence checker: PASS.
- Relocated retained-evidence checker: PASS.
- Tampered-evidence rejection: PASS.
- Focused Go tests and vet for the new guest, cell, payload, and gate: PASS.
- Full `make runtime-verify`: Go build, race tests, vet, 114 Python tests, and
  retained Codex-isolation, integrated-KVM, and DeathStar checks all PASS.
- `git diff --check`: recorded after final regression execution.

## Next action

Turn the process/container/Firecracker choices into one ordinary agent-runtime
launcher and expand mediation beyond declared MCP calls. The durable host
boundary should remain unchanged while the isolation backend becomes a policy
choice.
