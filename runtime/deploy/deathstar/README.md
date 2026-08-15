# DeathStarBench safe-change run

`run.sh` executes one fail-closed, end-to-end run against two pinned releases
of the unmodified DeathStarBench Hotel Reservation application. It builds the
official source at `hotelReservation-0.2.2` and `hotelReservation-0.3.5`, starts
the complete 0.3.5 Docker Compose service graph, and runs three matched
conditions around a one-night reservation whose committed response is lost.

The raw-retry condition duplicates the MongoDB row. The old-version-drain
condition avoids a duplicate only by remaining unavailable with the old
frontend and effect adapter retained. The runtime condition removes both old
processes, changes its Requirement, restarts the control process, observes the
application-owned MongoDB fact, and completes without another delivery. A new
call then uses the new frontend and adapter.

Prerequisites are Docker with Compose v2, Git, Go, curl, jq, and Python 3. Run:

```sh
runtime/deploy/deathstar/run.sh
```

Set `EVIDENCE_DIR` to retain evidence at a chosen path. Otherwise the script
creates and prints a directory under `/tmp`; evidence is never removed by the
cleanup trap. Set `KEEP_DEMO=1` only for interactive inspection. The script
uses the fixed Compose project `safe-change-deathstar-step15` and refuses to
start if resources with its exact names already exist.

The retained repository result is checked without starting Docker:

```sh
make runtime-deathstar-check
```

The checker does not import this runner. It independently replays the binary
History and joins it to raw Mongo, source, container, removal, and network
evidence. Its mutation tests must reject altered History bytes, request bodies,
Mongo facts, observer identities, final Rules, and Docker topology.
