# Result review

Verdict: **APPROVE**, scoped to one registered ordinary HTTP action across
complete Firecracker loss.

## Final run

The accepted run used official Claude Code 2.1.233 in thirteen distinct
Firecracker 1.16.1 microVMs with Linux 6.1.155. Every VM had no NIC, no root
block device, and the same read-only payload. Claude used its built-in Bash
tool and an ordinary local HTTP request. Neither Claude nor DeathStarBench was
modified.

The receiver was the full pinned DeathStarBench Hotel Reservation 0.3.5 graph
at commit `6ecb09706140f8730b5385c08f1386c654c3c526`: 23 official Compose
services plus an unmodified separately connected frontend from the same tree.

The accepted three-run matrix is:

| condition | Mongo rows per run | task completed |
|---|---:|---:|
| protected History recovery | 1, 1, 1 | yes |
| raw retry | 2, 2, 2 | yes |
| stop after loss | 1 | no |

For each protected run, the source VMM sent the reservation request, the
application committed it, a read-only Mongo observer found the row, and the
supervisor killed and reaped the exact VMM before any response byte returned.
The replacement VMM queried the existing application fact through History,
completed the same Operation, and returned `DONE` without another application
delivery. An explicit request through the old generation failed with HTTP 502
and `sandbox endpoint generation changed`.

## Repaired external oracle

The first complete run was rejected because the driver retained only its own
Mongo row counts. The database volume was later deleted, so an independent
checker could not reconstruct the primary oracle. That run remains under
`full-attempt-2-missing-oracle/` and is not accepted evidence.

The repair makes each Mongo aggregation return the exact bounded count and all
matching business-row summaries. Before cleanup, the driver retains all 19
queries in `raw/runtime/observer-facts.json`. Each record contains the
Operation ID, request hash, count, rows, row hash, outcome, and observation
time. Its SHA-256 is
`fface3c75a539042f30be7e39b405b3c88ce817e386b801dd69d0815766d1a0e`.

The independent checker imports no producer code. It reconstructs the expected
business rows and hashes, parses and rehashes binary History, recomputes
Operation and request identities, and joins the Mongo facts to the application
audit, fault timeline, Firecracker API records, VMM process identities, relay
byte counts, and Claude streams. Its SHA-256 at review was
`9c2b3596d3c23a99a2265b9135c4cb8df624152a837d2af52248d19d688d5435`,
and it returned `valid=true` on the accepted evidence.

## Failure ordering

All three protected runs satisfy:

```text
application commit <= Mongo observation <= fault barrier
                   <= source VMM stopped <= supervisor event
```

Each source HTTP relay recorded 363 guest-to-host bytes and zero
host-to-guest bytes. Source cells contain no guest result. The protected
History contains three distinct Operations, each following
`prepared -> dispatched -> unknown -> succeeded`, with settlement by query.

The checker also verifies the corresponding commit, Mongo observation, VMM
stop, and completion order for every raw run and the stop control.

## Development failures

Failed preflights and both rejected complete attempts remain alongside the
accepted result. They found incremental payload, Bash-loader, Claude stdout,
DeathStar credentials, session binding, KVM group, and missing-oracle defects.
The number of preflights exceeded the intended three-attempt research-workflow
limit; this is a process failure, not evidence for the accepted result.

## Interpretation and limits

The result closes one important mechanism gap: an unchanged Agent can use an
ordinary built-in tool and ordinary HTTP while a host runtime preserves an
external action across complete loss of its sandbox. Firecracker supplies the
failure and isolation boundary; History, Operation identity, generation
fencing, and application observation supply correctness.

This is not a production-deployment, performance, or arbitrary-network claim.
The experiment covers one operator-registered plaintext HTTP route, one fixed
request schema, one queryable application action, and a deterministic model
endpoint. It does not cover arbitrary HTTPS or sockets, receiver-side
idempotency as a baseline, remote attestation, device DMA, or fleet control.
