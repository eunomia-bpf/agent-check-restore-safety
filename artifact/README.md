# Executable authority-continuity validation

This directory contains a dependency-free Python model of the paper's finite
authority-continuity state.  It is executable validation, not a mechanized
proof.  In particular, passing bounded enumeration does not replace the paper
proofs or the planned Lean development.

Run the unit tests and deterministic exhaustive explorer from this directory:

```sh
python3 -m unittest -v
python3 explore.py
```

To save the canonical machine-readable report:

```sh
python3 explore.py --output results/exhaustive.json
```

The explorer enumerates every nonempty downward-closed frontier family on one
to three branches, scalar claim weights 1--2, durable demand 0--1, and grants
0--7.  It checks:

- the universal-frontier and componentwise-need formulations of AC agree;
- maximal single-claim promotion support is nonempty, downward closed, safe,
  and contains every safe downward-closed topology restriction;
- maximal repairs for disjoint claim batches are independent of serialization;
- identical snapshot-local Reserve observations require opposite decisions in
  replace and live-restore worlds; and
- plain escape can turn a safe exclusive choice into an unsafe state.
