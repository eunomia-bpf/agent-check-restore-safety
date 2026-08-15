# Step 0015 fixed experiment plan

Date: 2026-08-15 UTC

## Research question and hypothesis

Can the runtime finish a non-idempotent external Operation after its response
is lost and the old application component is deleted, using a frozen query
contract and external facts instead of resending the Operation?

Hypothesis: for the registered one-night DeathStarBench reservation workload,
an exact observation of the official MongoDB state can settle an unknown
Operation after a real frontend replacement. The proposed runtime will produce
one reservation document and finish the request without retaining the old
frontend. A raw-retry baseline will produce two matching documents. If the
observer sees zero, multiple, or only part of the expected facts, the runtime
will keep the Operation unknown and refuse to invent a result.

## Fixed system and versions

- Upstream application: DeathStarBench Hotel Reservation.
- Old frontend: tag `hotelReservation-0.2.2`, commit
  `25ccc81c1f6a1e7fe4d6b726d6a310cd2b607fa9`.
- New frontend and backend graph: tag `hotelReservation-0.3.5`, commit
  `6ecb09706140f8730b5385c08f1386c654c3c526`.
- Application source and images are built from those detached commits without
  source edits. Only a fixed ingress/executor and a read-only Mongo observer
  are project code.
- Registered success slice: one hotel, one night, one room, and a unique
  `customerName` derived from the stable Operation identity. Claims do not
  extend to arbitrary DeathStarBench requests.

## Conditions

1. **Raw retry:** send the same one-night reservation twice after dropping the
   first response. This is the real application's ordinary non-idempotent
   behavior and should leave two matching Mongo documents.
2. **Old-version drain:** after the same response loss, do not retry and retain
   the old frontend while waiting for a response that can no longer arrive.
   This preserves one database effect but cannot finish the request.
3. **Queryable runtime:** record dispatch, let the official application commit,
   drop the response, delete the old frontend, activate the new Rule, query the
   official Mongo state, and finish without redispatch.
4. **Inconclusive controls:** query a never-executed identity and the duplicated
   raw-retry identity against the real database; both must remain inconclusive.
   Mutated partial evidence must also fail in the offline checker. A multi-night
   request is rejected before dispatch rather than fabricating a partial commit.

## Fault and change timing

The loss point is deterministic: the executor waits for the official frontend
to return success, then closes its downstream HTTP connection before returning
the receipt. The old frontend is then removed and its container death is
recorded before the query. No random fault placement is used for the primary
result. The runtime control process is restarted over the same History before
recovery. The new frontend uses a distinct upstream commit and image ID.

## Measurements and oracle

- exact Mongo documents matching the Operation-derived customer identity;
- external deliveries and successful upstream responses;
- History events, head, frozen effect/query contracts, and query evidence;
- old/new source commit, image ID, container ID, mounts, and removal time;
- whether a second effect dispatch occurred;
- recovery latency and old-version retention time;
- standalone Certificate verdict and a downstream evidence checker verdict.

The live runner may not decide correctness from its own summary. A separate
checker must replay the binary History, join it to raw Mongo and Docker
evidence, verify both upstream commits and all digests, and reject changed
History bytes, query identity/request hash/fact hash, Mongo documents,
container timeline, or a fabricated second dispatch.

## Admission and kill criteria

Admitted because this adds a missing runtime capability (`Queryable`) and a
real non-idempotent database effect; merely starting the application would not
count. The milestone fails if any of the following is true:

- the official reservation/frontend source must be patched;
- correctness comes from a new idempotency table in project code;
- the proposed condition sends the reservation twice;
- the old frontend remains runnable or mounted into the new frontend;
- an inconclusive observation becomes success or failure;
- the raw-retry baseline does not demonstrably duplicate the Mongo effect;
- the evidence checker shares the live runner's decision code;
- ordinary verification or retained prior evidence stops passing.

This plan does not claim a maintained-application result, real payment, full
workflow migration, performance, or general exactly-once execution. Online
Boutique and Restate/Temporal remain separate later milestones.
