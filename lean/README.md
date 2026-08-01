# Authority Continuity Lean Development

This directory contains the Lean 4 mechanization used as supporting evidence
for RQ3.  Its scope is the finite abstract authority model, selected
certificate obligations, the closed lifecycle transition relation, and the
conditional trace-level authority theorem.  It is not an implementation or a
proof about an unmodified agent product.

## Pinned environment and reproduction

- Lean: `v4.30.0` (pinned by `lean-toolchain`)
- Mathlib: `v4.30.0` (pinned by `lake-manifest.json`)
- Build system: Lake

The caller must place the pinned `elan`/Lean tools on `PATH`.  A caller using an
isolated toolchain installation should set its own `ELAN_HOME` before invoking
the commands; no repository script overrides it.

```sh
cd lean
lake clean
lake exe cache get
lake build AuthorityContinuity
./scripts/audit.sh
```

`audit.sh` scans project Lean sources for proof placeholders and project
axiom/constant declarations, checks that every frozen theorem is declared,
builds the library, executes all `#print axioms` commands in
`AuthorityContinuity/Audit.lean`, retains their raw output in
`results/axioms.log`, rejects `sorryAx` and every dependency outside
`propext`, `Quot.sound`, and `Classical.choice`, and finally replays
`AuthorityContinuity.Main` with `leanchecker --fresh`.

## Frozen paper-facing theorem matrix

| Lean theorem | Mechanized obligation |
|---|---|
| `checkAC_sound` | The executable finite AC checker implies semantic authority continuity. |
| `guardClosure_iff` | Membership in the exact promotion guard is equivalent to old membership plus the promoted load bound. |
| `simulation_preserves_ac` | A certified target whose configurations project to no-heavier solvent source configurations satisfies AC. |
| `restriction_preserves_wf_ac` | Explicit support-preserving, load-decreasing restriction preserves well-formedness and AC. |
| `prepare_preserves_wf_ac` | Exact promotion and cleanup preserve well-formedness and AC without assuming either property of the target. |
| `ticket_step_preserves_wf_ac` | Ticket-only dispatch, retry, crash, and settlement preserve well-formedness, AC, and the stable operation binding. |
| `step_preserves_wf_ac` | Every constructor of the abstract lifecycle `Step` preserves well-formedness and AC. |
| `trace_preserves_wf_ac` | The reflexive-transitive closure of `Step` preserves well-formedness and AC. |
| `effect_coverage` | Finite stable operation IDs injectively bound to durable claims, with aggregate actual demand bounded per claim, consume no more than total durable demand. |
| `concrete_trace_authority_safety` | Under explicit mediation and forward-simulation premises, actual protected effects plus any currently permitted conditional bundle fit within capacity. |

The names and logical roles above are frozen by the approved RQ3 experiment
plan.  Reserve and direct-admission Merge expose executable target-AC checks.
Restriction, Prepare, and ticket cases derive their targets without target
AC/WF premises.  The generic topology case does not take a bundled `LWF A'`
premise, but `TopologyShape` supplies the target empty/downward/support/open
facts fieldwise; only target AC is derived from source AC and load simulation.
The independent experiment review therefore classified the result as mixed,
not a mechanization of the paper's full derived topology semantics.

Two audited auxiliary theorems, `trace_terminal_mono` and `trace_epoch_mono`,
lift one-step terminal-ID and branch/grant epoch monotonicity over the same
abstract trace closure.  They establish non-resurrection only for the modeled
transition system.  The audited `step_attempt_safe` theorem separately proves
that an admitted `attempt(e,c)` step has `opClaim(e)=c` and durable status for
`c` in its pre-state, and retains that binding in its immediate successor.
`step_preserves_existing_binding`, its trace lift, and
`SimulatedTrace.attempt_binding_final` prove that this stable binding survives
the remainder of the same simulated prefix.

## Concrete theorem assumptions

The concrete trace theorem is conditional.  Its arguments make the following
deployment obligations visible:

1. every relevant protected operation is included in the finite stable-ID
   operation set (every nonzero actual outcome is covered);
2. the exact `attempt(e, claimOf(e))` event occurs in the supplied simulated
   trace for each protected stable ID;
3. retries sharing a stable ID have an aggregate actual resource outcome no
   larger than that claim's declared demand;
4. every concrete step in `SimulatedTrace` is either an abstraction stutter or
   one admitted labeled abstract step, so attempt witnesses and the abstract
   lifecycle proof refer to the same concrete execution; and
5. the queried branch configuration is currently permitted by the abstract
   durability contract.

These are hypotheses, not conclusions about current Claude, Codex, or another
runtime.  In particular, the development does not establish that optional
hooks completely mediate tools, that a natural-language action was bound to
the right claim or demand, or that a remote sink reports its outcome truthfully.
Within a supplied `SimulatedTrace`, however, stable binding and
durable-before-attempt are derived from the lifecycle rules: tau stutters must
have zero outcome, an attempt event maps to the exact abstract attempt label,
and later steps cannot erase or rebind its operation ID.

## Deliberate non-claims

This RQ3 development does not mechanize Boundary I or Boundary II, general
pseudo-Boolean proof-object checker completeness, a real runtime adapter,
liveness, authority reclamation, or truthful external receipts.  It also does
not claim that checkpoint/restore by itself enforces non-resurrection: that
property holds only for transitions represented by the model and persistent
facts exposed through the stated refinement assumptions.

The topology constructor is deliberately generic: it checks an
identity-preserving conditional topology simulation, and direct Merge checks a
well-formed target plus executable AC.  The development does **not** mechanize
the paper's canonical choice/parallel Fork, replace/live Restore shape
predicates, `Mono₀(π)`, the `ρ` transfer map and fiber-conservation conditions,
or fragment issuance.  It must therefore not be described as a mechanization
of the paper's full checkpoint/fork/restore/merge syntax.

Lean foundational dependencies introduced by finite-set extensionality or
Mathlib (`propext`, `Quot.sound`, and `Classical.choice`) are permitted and are
reported rather than hidden.  A project-declared axiom or any other
foundational dependency requires a reviewed plan deviation.
