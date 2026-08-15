# Step 0008: broaden to a real cross-domain runtime

**Gate:** BOOTSTRAP
**Date:** 2026-08-15
**Status:** first vertical slice complete; larger goal active

## Recovery context

The repository entered this step with a mechanized finite Agent-history theorem,
an exact Python compiler/verifier, and a narrow Codex App Server adapter. The
user explicitly changed the objective to a real OS-like runtime spanning
Codex/Claude, full virtual machines, and microservices, with both theory and
systems breakthroughs.

The prior Agent result is preserved as a special case. It is not treated as the
complete scientific contract.

## Root disposition

Build a small control kernel above Linux/KVM rather than a new general-purpose
OS. The long-term result is safe change after external operations: derive what
must remain true from actual execution, synthesize a Rule using established
control theory, and enforce it at one cross-domain external-action boundary.

Only five public terms are retained: History, Requirement, Operation, Rule, and
Certificate.

## Closest-work correction

Fresh primary-source review found that several tempting headline claims are
already established:

- maximal nonblocking supervision and distributed localization;
- complete dynamic controller update and live completion of old obligations;
- state transfer and property-preserving updates;
- stable request identity, result reuse, and output commit;
- safe network update synthesis and several coordination boundaries; and
- impossibility of resolving an unobservable remote acceptance from local
  history alone.

The surviving research boundary is automatic derivation from real History plus
concrete cross-domain enforcement, not a new name for controller synthesis.
The detailed contract and sources are recorded in `docs/system-contract.md` and
the 2026-08-15 section of `docs/background-related-work.md`.

## System work completed

Added a Go runtime slice with:

- a synced, hash-linked, single-writer History with strict recovery;
- a History-head anchor that rejects an older valid file when kept outside the
  restored storage domain;
- stable Operation identities and frozen semantic bindings;
- bounded analysis of all outcomes of open Operations, exact inside the
  implemented stable-retry subclass;
- an exact finite completion planner over required results and resources;
- Rule activation bound to the complete History head;
- durable prepared/dispatched/unknown/settled phases;
- an HTTP Operation gateway with registered receipt semantics and no redirect
  following;
- a loopback-only control daemon with separate administration and per-adapter
  credentials bound to domain and allowed kinds; and
- a separate HTTP payment durability file used by an end-to-end demo process.

The demo commits one payment, loses the response, reopens the control object,
and safely reuses the same Operation. It observes two network deliveries and
one remote commit. It also blocks an individually valid action that would make
a required payment impossible and rejects a stale Certificate after Operation
progress.

## Reproduction

```sh
make runtime-build
make runtime-test
make runtime-demo
make runtime-verify
```

Observed demo facts in this step:

```text
blocked_stranding_action: true
first_network_result: unknown
recovered_result: succeeded
remote_deliveries: 2
remote_commits: 1
stale_certificate_rejected: true
```

Final verification for this step:

- 50 Go tests, plus the full race detector and `go vet`;
- 59 existing adapter tests; and
- 81 existing artifact/compiler/verifier tests.

All passed. Lean was not rerun because `lake` is unavailable in the current
shell; the prior checked build remains separate evidence rather than a new
result from this step.

## Honest boundary

This step does not yet provide VM enforcement, Codex/Claude integration into the
new runtime, replicated control, a symbolic solver, an independent checker
binary, or an end-to-end Lean refinement. The current planner is a bounded
system seed and regression oracle, not the claimed theoretical novelty. It
fails closed outside its implemented stable-retry subclass; query-based
recovery is not yet counted as available.

Adversarial review found and forced corrections for false semantic settlement,
History rollback, concurrent duplicate dispatch, ambiguous request hashing,
failed write recovery, unversioned replay, unbounded solver work,
caller-asserted domains, and raw response retention. The current HTTP adapter
settles only a strict receipt bound to the Operation identity; 202, 5xx,
redirects, and unrecognized 2xx responses remain unknown. The head anchor must
live outside the protected restore domain, and the current API still does not
prevent same-user host bypass.

## Next decisive step

Build the first enforced multi-service workload and separate the compiler from
the checker. In parallel, add a QEMU/virtme smoke target that demonstrates the
host can launch a complete guest and route its protected network action through
the same Operation identity.
