# Preflight attempt 2 disposition

- Result: **failed after the first guarded `InstanceStart`, with zero recorded
  effect-adapter deliveries**.
- Retained evidence: `preflight-attempt-2/`.
- What passed: the protected guard authorized the exact configured H1 source;
  Firecracker reached `ready`; official Claude reached the model; the effect
  proxy durably recorded `prepared -> dispatched`; the effect-adapter audit
  remained empty; all processes were reaped. No terminal Mongo observation
  was retained, so this attempt supports no broader no-commit claim.
- Exact failure: the first host-to-DeathStarBench reservation request had not
  returned within the producer's 30-second delivery wait. Cleanup then closed
  the in-flight path, producing `unknown`. The run did not retain the temporary
  cell directory, so it is insufficient to distinguish a slow application
  dependency from the final host relay hop.
- Safety disposition: zero effect-adapter deliveries were recorded and no
  residual VMM remained. This is not a positive or negative scientific result.
- Required corrections before attempt 3: always archive partial cell evidence
  on failure, and exercise the complete frontend-to-reservation dependency
  chain with a separately identifiable customer before any measured lane.
