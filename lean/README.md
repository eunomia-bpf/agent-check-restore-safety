# Authority Continuity Lean Development

This directory contains the Lean 4 mechanization used for the paper's VQ1
formal validation.  Its scope is the finite abstract authority model, selected
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
`AuthorityContinuity/Audit.lean`, writes their raw output to generated
`results/axioms.log`, rejects `sorryAx` and every dependency outside
`propext`, `Quot.sound`, and `Classical.choice`, and finally replays
`AuthorityContinuity.Main` with `leanchecker --fresh`.
For the current history-admission and information-lower-bound additions, the
complete `Audit.lean` elaboration/axiom allowlist and the full fresh replay of
`AuthorityContinuity.Main` pass.

## Frozen paper-facing theorem matrix

| Lean theorem | Mechanized obligation |
|---|---|
| `PaperTheorems.exact_checker_iff_realization` | Executable greatest-fixed-point admission is equivalent to the independently stated declarative realization predicate. |
| `PaperTheorems.registered_workflow_exact_admission` | Typed workflow compilation composes accepted registration, exhaustive mediation, compiled/semantic contract equality, and exact admission. |
| `PaperTheorems.six_edit_derivation_exact` | The executable derivation function is sound and complete for Choice/Parallel Fork, Replace/Live Restore, and Select/Join Merge. |
| `PaperTheorems.compilation_preload_preserves_agentSec` | Compilation preloading is an explicit kernel transition that records inactive candidate metadata and preserves `AgentSec`. |
| `PaperTheorems.exact_edit_installs_trace_safe_monitor` | An admitted derived edit constructs a valid atomic installation whose every finite continuation preserves `AgentSec`. |
| `PaperTheorems.fresh_alias_installation_serialized` | Fresh use, alias use, and installation admit exactly the two durable orders: prior use stales the candidate; prior installation denies the old use. |
| `OperationalSemantics.editedContractAt_spec` | Successful authenticated editing returns the registered edited contract, partitions source promises into satisfied/authorized-removed/still-required outcomes, supplies a `Covers` witness for each still-required outcome, and authenticates each removal. |
| `CompilationBridge.compileInstallCandidate_installs_editedContract` | The compiler checks the edited contract and atomic installation stores that same contract. |
| `InformationLowerBound.exactView_iff_refines_answerSignature` | An arbitrary record representation is exact exactly when it refines equality of all checker answers; no raw field layout is assumed. |
| `InformationLowerBound.fourFactor_exactView_card_lower_bound` | Every finite exact view of independent promise, identity, edit, and current-cut answer dimensions has at least 16 answer classes. |
| `InformationLowerBound.exactView_separates_each_dimension` | Every exact view separates an answer-changing pair for each of the four dimensions. |
| `checkAC_sound` | The executable finite AC checker implies semantic authority continuity. |
| `guardClosure_iff` | Membership in the exact promotion guard is equivalent to old membership plus the promoted load bound. |
| `simulation_preserves_ac` | A certified target whose configurations project to no-heavier solvent source configurations satisfies AC. |
| `restriction_preserves_wf_ac` | Explicit support-preserving, load-decreasing restriction preserves well-formedness and AC. |
| `prepare_preserves_wf_ac` | Exact promotion and cleanup preserve well-formedness and AC without assuming either property of the target. |
| `ticket_step_preserves_wf_ac` | Ticket-only dispatch, retry, crash, and settlement preserve well-formedness, AC, and the stable operation binding. |
| `checkTransfer_sound` | The finite transfer checker implies exact domain, preallocated-fragment provenance, grant agreement, owner projection, and coordinatewise fiber conservation. |
| `topology_fiber_conservation` | A checked transfer makes every target conditional load no larger than its projected source load. |
| `choiceFork_preserves_wf_ac` / `parallelFork_preserves_wf_ac` | Exact computed choice/parallel Fork targets preserve lifecycle WF, AC, and active-support exactness. |
| `replaceRestore_preserves_wf_ac` / `liveRestore_preserves_wf_ac` | Exact computed replacing/live Restore targets preserve the same invariants. |
| `simulation_merge_preserves_wf_ac` | Atomized structure, `Mono_0`, and simulation checks derive safe explicit Merge targets without checking target AC. |
| `direct_merge_preserves_wf_ac` | The separate direct Merge mode uses the same structure checker and explicit target AC admission. |
| `step_preserves_wf_ac` | Every constructor of the abstract lifecycle `Step` preserves well-formedness and AC. |
| `trace_preserves_wf_ac` | The reflexive-transitive closure of `Step` preserves well-formedness and AC. |
| `effect_coverage` | Finite stable operation IDs injectively bound to durable claims, with aggregate actual demand bounded per claim, consume no more than total durable demand. |
| `concrete_trace_authority_safety` | Under explicit mediation and forward-simulation premises, actual protected effects plus any currently permitted conditional bundle fit within capacity. |
| `classifyAdmission_sound` | The typed Fork/Restore/Merge classifier returns only inheritance, full readmission, pruning repair, or rejection justified by its semantic predicates. |
| `hereditarySafeCoLiveRestriction_subset` / `hereditarySafeCoLiveRestriction_downwardClosed` / `hereditarySafeCoLiveRestriction_rawPhysical_safe` | Filtering `Gamma` by `SafeGroup(G) := RawPhysical(G.powerset) <= Admitted` removes no outside group, preserves downward closure, and leaves only admitted physical behavior. |
| `hereditarySafeCoLiveRestriction_greatest` / `required_subset_hereditarySafeCoLiveRestriction_iff_exists_deploymentReady` | The filter is the greatest downward-closed, physically safe subfamily of `Gamma`; it covers `Required` exactly when some downward-closed deployment-ready restriction of `Gamma` exists. |
| `prefixThenControllerRepair_greatest` | Composing the greatest durable-prefix filter `safeFuture` with the greatest hereditary-safe controller filter is jointly principal: every prefix-safe candidate pruning and subordinate safe controller repair embeds in the computed two-level repair. |
| `deploymentReady_iff_required_coverage_and_avoids_obstructions` | Raw controller-product readiness is exactly required coverage plus avoidance of support escape and realizable minimal nonfaces. |
| `rawPhysicalCoverProduct_has_card_bounded_plan` | Every physical realization of a cell configuration `C` can be compressed to at most `|C|` active controllers when co-liveness is downward closed. |
| `deploymentReady_iff_of_contract_observation` | Two downward-closed controller realizations with the same co-liveness projection through a contract bound have the same readiness decision. The bound covers maximum required size, maximum admitted minimal-nonface size, and unary outside-support witnesses. |
| `deploymentReady_iff_of_contractObservationArity_projection_eq` | The preceding sufficiency theorem instantiated with the finite maximum computed directly from the required and admitted families. |
| `coLiveProjection_downwardClosed` / `coLiveProjection_idempotent` | A complete bounded projection is downward closed and is unchanged by projecting it again at the same arity. |
| `deploymentReady_iff_contractProjection` / `deploymentReady_iff_of_attested_exact_projection` | Tool-facing exactness: checking the complete contract-indexed projection itself yields the hidden downward-closed realization's readiness bit; the adapter-facing form keeps exact projection completeness as an explicit attestation premise. |
| `forbidden_valid_cover_cases` | Every forbidden controller cover is honestly classified as outside-support, local overpermission, or a locally admitted correlation cut. |
| `actual_prefixConfigMorphism_of_deploymentReady` | Under `Required <= Actual <= RawPhysical`, manifest readiness transports the admitted durable-prefix certificate to the actual runtime family. |
| `rawPhysical_partition_eq_localProduct` / `canonicalPartition_deploymentReady_iff_mustCoordinate` | The canonical one-controller-per-cell adapter is a proved instance of the relational model, and its readiness criterion reduces to `MustCoordinate`. |
| `split_controllers_admit_forbidden_triple` | A finite U(2,3) fixture exposes a higher-order correlation cut that every pairwise check misses. |
| `no_pairwise_observation_checker_exact` | Two downward-closed realizations agree on every input through complete pairwise co-liveness but require opposite readiness decisions. |
| `ArbitraryArity.contractObservationArity_rankFamily` / `ArbitraryArity.no_lower_arity_downwardClosed_observation_checker_exact` | For positive `k`, the computed contract maximum of `U(k,k+1)` is exactly `k+1`, local choices are sound, and the unsafe full configuration is a genuine correlation-cut witness; for every `k`, downward-closed safe/unsafe realizations agree through complete arity-`k` co-liveness observation but require opposite readiness decisions. Thus the upper bound is worst-case arity-tight. |

The legacy lifecycle names and logical roles above are frozen by the prior
mechanization plan; the history-admission and controller-cover rows freeze the
new compiler-facing theory layer.  Reserve and direct-admission Merge expose
executable target-AC checks.

`RuntimeCertificate.lean` separately defines the finite semantics used by the
new Go Certificate checker: all open-Operation outcome worlds, bounded
completion, the canonical largest Rule, and mutually exclusive activate and
impossible decisions.  Its audited theorems prove the semantic checker exact
for that model.  They do not yet prove that Go projection construction, JSON
decoding, hashing, or numeric limits refine the Lean definitions.
Restriction, Prepare, ticket cases, and the four canonical Fork/Restore cases
derive their targets without target AC/WF premises.  Canonical checkers inspect
only source-local freshness, transfer, and owner facts; the exact target
contract and epochs come from the operation builder.  An independent result
review classified this finite abstract-topology experiment as positive.

The observation-arity result is contract indexed, not a claim that one global
arity is necessary for every runtime.  For fixed access and local families,
the computed upper bound is

```text
max(maximum required-configuration size,
    maximum admitted minimal-nonface size,
    1 when a cell exists outside admitted support, else 0).
```

Its proof uses downward closure twice: co-liveness permits shrinking any cover
to one contributing controller per realized cell, while local-family downward
closure turns an arbitrary forbidden realization into either a realizable
minimal nonface or a realizable outside-support singleton.  The arbitrary-`k`
fixture is a worst-case necessity theorem, not a claim that this conservative
contract-only maximum is minimal for each concrete access/local-family
manifest.

The controller repair is also canonical under the paper's stated control
boundary.  For each active group `G`, `SafeGroup(G)` checks the raw product of
the entire powerset of `G`, not only the maximal group.  Filtering a supplied
downward-closed co-liveness family `Gamma` by this predicate yields
`Gamma*`: a downward-closed safe restriction that contains every other
downward-closed safe `Delta <= Gamma`.  Consequently, required behavior
survives `Gamma*` exactly when any deployment-ready co-liveness pruning can
preserve it.  This maximality assumes the runtime can disable co-liveness
groups; it does not synthesize new access paths or controller-local choices.
The `prefixThenControllerRepair_greatest` theorem links this controller-level
principal repair to the earlier configuration-level `safeFuture` filter.

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

This development does not mechanize Boundary I or Boundary II, general
pseudo-Boolean proof-object checker completeness, a real runtime adapter,
liveness, authority reclamation, natural-language binding correctness, issuer
approval, or truthful external receipts.  It also does not claim that
checkpoint/restore by itself enforces non-resurrection: that property holds
only for transitions represented by the model and persistent facts exposed
through the stated refinement assumptions.

The four canonical topology constructors cover exact choice/parallel Fork and
replacing/live Restore.  Their `rho` fibers can split a tentative source claim
only into identifiers that already exist in the fixed finite type and are
`unissued` in the source; the development does not prove truly dynamic
identifier-space extension.  Arbitrary Merge is intentionally explicit: an
atomized finite checker validates target structure, and the simulation mode
checks `Mono₀(π)` plus per-configuration dominance while direct admission
separately invokes target AC.  These facts support a finite abstract lifecycle
claim, not a full production-runtime refinement.

The audit regenerates build and axiom logs under `results/`; these outputs are
not shipped in the anonymous supplement.  The paper-facing evidence is the
pinned source, the frozen theorem list, and reproducible build/axiom checks.

Lean foundational dependencies introduced by finite-set extensionality or
Mathlib (`propext`, `Quot.sound`, and `Classical.choice`) are permitted and are
reported rather than hidden.  A project-declared axiom or any other
foundational dependency requires a reviewed plan deviation.
