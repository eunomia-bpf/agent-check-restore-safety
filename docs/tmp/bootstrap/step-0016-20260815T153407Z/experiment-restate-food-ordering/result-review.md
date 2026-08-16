# Result Review: RQ4 Real Program Replacement

## Decision

**Freeze the experiment and its raw evidence.** The central hypothesis is
supported within the registered, queryable HTTP-provider scope. No successful
matrix needs to be rerun. The remaining work is documentation and a broader
host-enforced VM boundary; it is not a repair to this result.

The same independent result reviewer that rejected the earlier evidence
rechecked the completed Restate and Temporal records. It found no new P0 and
closed the two scientific blockers: Restate old-version continuation is now a
real resumed execution, and the Temporal port now runs the complete business
workflow.

## Decisive result

Five proposed-system H0/H1 pairs start from the same Restate journal and
workflow state and use the same target program. The durable external fact is
the only intended difference:

- H0 has no committed payment. The runtime returns `impossible`, does not
  start the target, and does not invent the still-required payment.
- H1 has one committed payment whose response was lost. The runtime queries
  that fact, records the existing Operation as succeeded, activates the target,
  fences v1, and reaches `DELIVERED` with one payment commit and one completion
  commit.

All five pairs returned these opposite decisions. Native version mechanisms
did not automatically make this distinction at the same cut.

## Executed matrix

| Cell | Repetitions | Independently checked result |
|---|---:|---|
| Proposed Restate H0/H1 | 5 pairs | H0 `impossible`; H1 `activate`; equal Restate cut; v1 fenced |
| Native Restate replacement | 5 pairs | Both histories encounter code-path mismatch and back off |
| Restate compatible control | 5 proposed/native pairs | Compatible target completes |
| Restate no-query ablation | 5 | H1 fails closed; target never starts; failed query does not change History |
| Restate unsafe target | 5 proposed/native pairs | Proposed refuses before target; native completes without Requirement enforcement |
| Restate old-version continuation | 5 H0/H1 pairs | Both reach `DELIVERED` on v1; H1 duplicates payment in 5/5 |
| Temporal manual branch | 5 H0/H1 pairs | H0 fails and H1 completes, but only through developer-written branching |
| Temporal AutoUpgrade | 5 H0/H1 pairs | Both remain running with two nondeterministic workflow-task failures |
| Temporal Pinned | 5 H0/H1 pairs | Existing runs remain dependent on v1 |
| Temporal compatible control | 5 | Full workflow completes as `compatible-v2` |
| Temporal old-version continuation | 5 H0/H1 pairs | Availability retained; target never starts; v1 remains required |
| Temporal unsafe target | 5 proposed/native pairs | Proposed refuses before target; native uses approval 2 with capacity 1 |

The new Temporal package contains exactly 55 real lanes: 30 main lanes, five
compatible lanes, ten old-version lanes, and ten unsafe lanes. Its complete
workflow includes restaurant and product selection, `ChargePayment`, the
durable schedule, `PrepareFood`, driver selection, driver arrival,
`ScheduleDelivery`, delivery completion, and `CompleteOrder`.

## Baseline interpretation

The old-version Restate control is a real availability baseline, not a safe
success. All ten executions resume the same invocation using the retained v1
deployment and reach a 27-entry journal ending in `DELIVERED`. H0 ends with one
payment commit. H1 already has one commit at the cut and executes payment
again, ending with two commits in 5/5 repetitions. Thus `valid: true` means the
evidence is internally valid; it does not mean that H1 satisfies the
Requirement.

Temporal manual branching also is not evidence that the proposed mechanism is
unnecessary. It reproduces the useful H0/H1 outcome only by retaining explicit
developer knowledge of the old execution. Pinned and old-version controls
retain old code. AutoUpgrade does not complete the incompatible replay.

## Integrity and independent checks

The final Temporal run started at `2026-08-16T07:36:07Z`, ended at
`2026-08-16T08:25:30Z`, and exited zero. Independent audit established:

- `5680/5680` recursive checksum entries match;
- all 28 command checkpoints exited zero;
- all 28 post-checkpoint resource snapshots contain zero scoped containers,
  networks, and volumes;
- all 30 main run IDs and evidence digests are unique;
- all five compatible run IDs and evidence digests are unique;
- Temporal old-version evidence has ten unique case digests, five unique pair
  digests, and ten unique run IDs;
- Temporal unsafe evidence has ten unique case digests, five unique pair
  digests, and twenty unique workflow run IDs;
- every stored main, compatible, old-version, unsafe case, pair, mutation, and
  full-check output was recomputed from raw records and matched byte for byte;
- the unsafe suites exercised 535 candidates: 525 decisive mutations were
  rejected and ten declared summary-only positive controls were accepted.

The complete `raw/` directory, including failed preflight attempts, is archived
as `artifacts/raw-evidence-20260816.tar.zst`. Its SHA-256 is
`5e12ce8ab5ed4bcddc248b3e0c699138d01fcf7aee4d280e02cfe80d69ca9a0f`.

## Earlier blockers

1. **Fake Restate old-version drain: closed.** Official resume output, the
   retained v1 process, the complete journal, and final provider records are
   present for all ten lanes.
2. **Simplified Temporal workflow: closed.** Raw Temporal History contains all
   payment, preparation, driver, delivery, and completion stages.
3. **Unexplained earlier Temporal failures: closed for the scientific result,
   incomplete for provenance.** A clean post-repair 55-lane matrix replaces
   those runs, but two early failure records remain incomplete as described
   below.
4. **Repository says “no result”: closed by this review and the accompanying
   `docs/evaluation.md` update.**

## Scope and provenance limitations

The result is decisive only for registered Operations with an authoritative,
honest, reachable query interface in this food-ordering workload. It does not
prove generic exactly-once execution, behavior with a dishonest or unreachable
provider, all Restate applications, arbitrary protocols, or production-grade
atomic cutover of an unmodified VM. The Temporal application is a matched port,
not an official Temporal food-ordering sample.

The fixed business Results and Capacities are unchanged across v1/v2, but the
complete Requirement JSON changes with the Operation catalog. Temporal main
lanes intentionally reuse a fixed business Operation identity inside isolated
Compose projects; their workflow run IDs, containers, and evidence digests are
unique, so Operation-ID uniqueness must not be claimed for those lanes.

Two failed-attempt records are incomplete and must not be reconstructed after
the fact:

- the first compatible mutation audit reported 34 passing tests and four
  stale-index `KeyError`s, but its exact stderr and the pre-repair test source
  were not retained; the repaired source was fixed before the full matrix and
  passes 38/38;
- the old `temporal-unsafe-v1` failure lacks enough original stderr/source
  provenance to establish its exact cause.

These gaps violate the plan's ideal failed-attempt provenance rule, but they do
not enter the accepted measurements: the post-repair full run, build inputs,
checkers, raw records, and recursive hashes are retained and reproducible.

## Paper-value judgment

The result supports a scoped system claim: History plus authoritative external
observation can safely automate replacement after an unresolved external
operation without per-instance migration and without retaining the old
program. Any paper use must report the old-version H1 duplicate payment and the
provider/workload boundaries above. It must not describe baseline `valid`
evidence as baseline safety.
