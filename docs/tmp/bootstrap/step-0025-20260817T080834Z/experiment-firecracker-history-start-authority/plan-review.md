# Independent plan review

Reviewer: fresh Step 0025 plan reviewer, read-only.

Final verdict: **APPROVE** after three review/fix rounds.

## Round 1: REVISE

The first plan was non-redundant and feasible, but did not freeze the exact
initial/target Requirements, confused whole-lane and replacement-only H0 start
counts, alternated between target-only and all-VM enforcement, overstated
same-UID API-socket exclusivity, and omitted exact commands, deadlines, process
counts, and the H0 `Not started` oracle.

The revision froze the two Requirements and their hash timing, normalized the
machine comparison, required History authorization for every protected source
and replacement start, scoped H0 zero events to its denied replacement, stated
the structural same-UID TCB limit, and fixed commands, paths, deadlines, and
resource counts.

## Round 2: REVISE

The second plan still let the same trusted binary select an unguarded baseline,
which contradicted exclusive start authority. Its history comparison also
failed to distinguish identical pre-recovery events from the necessarily
different succeeded/failed recovery update.

The revision separated the protected and baseline launchers by admitted
executable name and hash, removed every unguarded mode from the protected
command, and froze History comparison as complete pre-recovery equivalence
after declared identity substitution plus only enumerated outcome-bound fields
in the recovery update.

## Round 3: APPROVE

The reviewer confirmed that Requirements, normalized machine configuration,
per-process chronology, source/replacement guarding, baseline separation,
same-UID limitation, commands, deadlines, H0 `Not started` checks, final
zero-row check, and reap requirements are now internally consistent and
executable. The optional suggestion to name Firecracker and the host Linux
kernel in the TCB was incorporated before implementation.
