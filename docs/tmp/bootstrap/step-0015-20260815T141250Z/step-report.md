# Step 0015: recover a committed operation after deleting v1

Date: 2026-08-15 UTC

## Outcome

Pass. The runtime recovered a non-idempotent reservation whose response was
lost after the unmodified DeathStarBench application committed it. Before
recovery, the runner activated Rule v2, removed the v1 frontend and v1 effect
process, started v2 replacements, and restarted control over the same History.
The old Operation was settled from one exact Mongo document and was not sent
again. A new Operation then completed through v2.

The retained History has sequence 9 and head
`b0e8953b290f6915552e38d260ee8c7c92d9418742caac62ecb430d15b0e1bcd`.
The independent checker returned `valid=true`.

## Fixed application

- DeathStarBench Hotel Reservation v1: tag `hotelReservation-0.2.2`, commit
  `25ccc81c1f6a1e7fe4d6b726d6a310cd2b607fa9`, subtree
  `9846449187fdeb286127885ab747cef24bdba3fd`.
- DeathStarBench Hotel Reservation v2: tag `hotelReservation-0.3.5`, commit
  `6ecb09706140f8730b5385c08f1386c654c3c526`, subtree
  `0ac0fd6d4ccfa1472d3895384d45fef5c6246b03`.
- Both source trees were clean before and after image construction.
- The runner started all 23 non-frontend services from the official 24-service
  v2 Compose definition and supplied separately built v1/v2 frontends.

## Matched conditions

| Condition | Deliveries | Commits | Mongo rows | Available | v1 retained |
|---|---:|---:|---:|---|---|
| Raw retry | 2 | 2 | 2 | yes, with duplicate effect | yes |
| Old-version drain | 1 | 1 | 1 | no result can return | yes |
| History query recovery | 2 | 2 | 2 | yes | no |

The proposed totals contain one old and one new Operation. The old Operation
has exactly one dispatch, one Mongo document, and `settlement="query"`; v2 had
zero deliveries before that recovery. The second delivery and document belong
only to the distinct new v2 Operation.

## Enforced trust cuts

Four Docker networks separate application, frontdoor, observation, and control
traffic. Raw inspection plus direct probes establish that:

- effect cannot resolve or reach reservation MongoDB;
- observer cannot resolve or reach frontend or reservation;
- control cannot resolve or reach frontend, reservation, or MongoDB;
- control can reach the protected effect and observer endpoints; and
- the v1 frontend/effect containers no longer exist while both v2 replacements
  are running.

## Independent validation

`adapter/check_deathstar_evidence.py` does not import the runner. It independently
replayed the binary History and external head, reran both standalone Certificate
checks, recomputed stable Operation identities and request/fact hashes, and
joined five observations to raw Mongo documents, source trees, images,
containers, removals, and network membership.

The checker test suite passed 16/16 tests: three derivation tests, the retained
real run, and twelve evidence mutations. Mutations cover History bytes, request
body bytes, Mongo count/content, observer identity/fact hash, upstream commit,
old-container removal, final Rule, official service graph, raw duplicate rows,
and network topology.

## Fail-closed controls

- A never-executed identity produced a real zero-count observation and remained
  inconclusive.
- The raw-retry identity produced a real two-count observation and remained
  inconclusive.
- A multi-night request was rejected before delivery because the registered
  observer contract covers exactly one stored night.
- The offline checker rejects partial or mutated evidence rather than inventing
  success.

## Limits and next decisive step

This run covers one hotel, one night, one room, and a unique customer derived
from the Operation identity. It proves the fixed positive commit-then-loss
History, not general exactly-once execution or liveness for every unknown
Operation. Zero and multiple matches stay unknown. The observer is local and
trusted, and changed code must still resupply the exact old request bytes; the
History currently retains their hash rather than their content.

DeathStarBench is a real unmodified microservice benchmark, but it is not the
primary maintained long-running workflow target. The next workload should use
the official Restate `food-ordering` application, with native Restate and a
matched Temporal Worker Deployment as strong baselines, then repeat the core
result on a second ecosystem such as Online Boutique.
