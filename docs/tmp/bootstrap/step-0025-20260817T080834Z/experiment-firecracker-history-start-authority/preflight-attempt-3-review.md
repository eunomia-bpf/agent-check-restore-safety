# Preflight attempt 3 disposition

- Result: **failed after the first guarded `InstanceStart`, before any recorded
  effect-adapter delivery**.
- Retained evidence: `preflight-attempt-3/`.
- What passed: a separately identifiable readiness reservation received an
  explicit success immediately before measurement, corroborating that the
  complete DeathStarBench dependency chain was healthy; the protected guard
  authorized the exact configured H1 source; Firecracker recorded one
  `InstanceStart` and reached `ready`; official Claude invoked the fixed Bash
  action; and the guest sent 363 bytes through both bound egress hops. The
  readiness request used the same hotel inventory and is not an isolated
  control workload.
- Exact observed failure: the guest received `HTTP/1.1 409 Conflict` after 783
  response bytes. History records the matching Operation as `prepared ->
  dispatched -> unknown`; the DeathStar adapter audit is empty, so it records
  zero application deliveries.
- Root cause: the gateway computed and recorded the Operation request hash but
  did not attach `X-Operation-Request-Hash` to the outbound effect request.
  The DeathStar effect adapter requires that header before application I/O;
  its rejection could not satisfy the registered receipt classifier, so the
  gateway conservatively recorded `unknown` and the outer effect proxy
  returned 409. The retained source manifest and protocol code establish this
  mismatch; the preceding readiness success corroborates, but does not by
  itself prove, dependency health at the later request.
- Safety disposition: fail closed within the declared TCB. The missing-header
  code path rejects before DeathStar upstream I/O, the adapter audit records
  zero deliveries, the configured Firecracker process was reaped, and the
  residual-process check found no live session.
- Scientific disposition: this is not an H1/H0/control result and is not
  admissible evidence. All three plan-authorized real preflight attempts are
  exhausted, so no fourth attempt or full matrix may run under this plan.
- Post-attempt correction: attach the already-computed digest only after hash
  computation, preserving the digest definition while binding the provider
  request to History. Regression tests now require the outbound header to
  equal the request hash retained in the Operation and exercise the exact
  gateway-to-DeathStar effect boundary. This correction has only regression
  evidence, not a passing real preflight.
