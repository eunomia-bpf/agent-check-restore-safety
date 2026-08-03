# General finite-core characterization result

Date: 2026-08-03

## Verdict

**PASS for the registered finite admission core.** The Lean development now
proves, for every finite registered instance, that the executable pruning
compiler admits exactly when a valid declarative realization exists. When one
exists, the computed language and indexed completion family are
componentwise greatest.

This result mechanizes the paper's resolver and greatest-realization core. It
does not yet mechanize the six history edits, P/I/E/C lower bounds,
genesis-based reachability, or durable weak bisimulation.

## Frozen source and toolchain

- Source:
  `lean/AuthorityContinuity/AgentHistoryAdmission/FiniteCore.lean`
- Source SHA-256:
  `cd939b2efc35cbff4ff7b1ea67bf5c0262f88471e03509babd39502459e471a5`
- Repository parent commit:
  `4828100`
- Lean: `4.30.0`
- Lake: `5.0.0`
- Mathlib: repository-pinned `v4.30.0`

Authoritative command, run from `lean/`:

```sh
ELAN_HOME=/home/will/.cache/agent-history-elan \
PATH=/home/will/.cache/agent-history-elan/bin:/usr/local/bin:/usr/bin:/bin \
lake env lean AuthorityContinuity/AgentHistoryAdmission/FiniteCore.lean
```

The independent replay completed with:

```text
wall_seconds=9.34
max_rss_kb=6813332
exit_status=0
```

A fresh reviewer also replayed the file with `--trust=0`; it exited zero with
only linter warnings. The source contains no `sorry`, tactic `admit`, project
`axiom`, or `unsafe`.

## Mechanized contract

The finite instance has one ordered durable receipt-cell ledger.
`initialReceipted` and `durablePrefix` are derived from that ledger rather
than supplied independently. Instance validity requires a prefix-closed
authority policy and a duplicate-free durable ledger.

The resolver has two independent presentations:

- the executable `resolveFrom`; and
- the inductive judgment `ResolvesFrom`, which carries the exact final receipt
  state.

Lean proves totality, exact graph equivalence, determinism, occurrence and
length preservation, Fresh-cell uniqueness, state-threaded streaming, and
authority-word streaming. It also proves that membership in the executable
candidate family is equivalent to relational candidate generation.

The declarative `Realization(I,L,B)` does not mention `Phi`, pruning, or a
compiler. It requires a nonempty indexed completion family, registered-history
fidelity, prefix authority safety, exact generated-language equality, and
persistent support for every outcome compatible with every admitted prefix.
`ValidRealization` adds exactly the registered-instance validity premises.

The executable side proves:

- `Phi` is monotone;
- iteration from `B0` is descending and stabilizes within `|B0|` rounds;
- `boundedFixedPoint = greatestPostfixed`;
- every realization is componentwise contained in the greatest fixed point;
- a realization exists iff the greatest fixed point is nonempty;
- the Boolean realization checker is equivalent to `ValidRealization`;
- `SemanticAns = admit` iff some valid declarative realization exists;
- `CompilerAns = admit` iff the same valid declarative realization exists; and
- `CompilerAns = SemanticAns` for every finite input, including fail-closed
  malformed policies and durable ledgers.

The literal shared-prefix fixture remains
\(X\parallel(Y\oplus Z)\) with
\(\mathcal A=\operatorname{Pref}\{yx,xz\}\). Its pruning cardinalities are
kernel-checked as `[2,1,0]`, and both routes reject.

## Audit history

The first general version passed compilation but failed an independent
nonvacuity audit. The audit found three real contract defects:

1. the inductive resolver lacked a totality theorem and was disconnected from
   candidate semantics;
2. the Boolean semantic route hid a policy-validity premise in a shared
   rejection gate; and
3. the receipt set and durable authority prefix were independently supplied.

The repaired version proves the resolver graph and candidate bridge, separates
core `Realization` from explicit `ValidRealization`, exposes public
admit-if-and-only-if theorems, and derives both cut views from one ledger.
A fresh read-only re-audit returned **PASS** and exercised six adversarial
finite instances, including a duplicate ledger and a deliberately
noncontractive arbitrary seed.

## Remaining boundary

The result ranges over finite registered outcome languages, mappings, and
policies. It does not derive those inputs from authenticated Agent history.
The full ranked deletion-cause certificate is also deferred rather than
represented by a weaker final-state witness.

The next decisive module is `OperationalSemantics.lean`: one empty genesis,
trusted registration, all six edits, complete modeled events, and arbitrary
finite-prefix preservation. The paper must not present this finite-core result
as a mechanization of the assembled Agent Security-State Characterization.
