# Independent Result Review: RQ3 Mechanized Lifecycle Core

**Review status:** mixed

**Reviewer role:** fresh, read-only result reviewer
**Technical replay:** source/statement scan, independent `#print axioms`, and `leanchecker --fresh AuthorityContinuity.Main`; no files modified

## Run status

The technical run is valid. All ten frozen constants are present, the clean 742-job build passed, the source contains no `sorry`, `admit`, or project-declared axiom/constant, and the reported dependencies are limited to `propext`, `Quot.sound`, and `Classical.choice`. An independent fresh kernel replay exited zero.

The scientific result is nevertheless mixed. The kernel checks the conditional theorems as stated, but the current topology interface does not independently derive all target structural well-formedness facts from canonical operation shapes.

## Hypothesis verdict

The narrow hypothesis is supported: executable AC admission, computed restriction, exact Prepare/cleanup, crash-aware ticket preservation, binding persistence, trace induction, and conditional effect coverage can be mechanized without proof placeholders or project axioms.

The broad hypothesis is not established. `TopologyShape` does not assume the proposition `LWF A'` verbatim, but its fields directly require the target's empty configuration, downward closure, tentative-owner support, open configurations, open owners, and open grants. `TopologyShape.target_lwf` then packages those facts with history-preservation fields into target lifecycle well-formedness. This is legitimate as an explicit logical certificate interface, but it is not a proof that canonical Fork/Restore/Merge construction or a certificate checker derives those fields from source state and operation shape.

The target AC result is stronger: `simulation_preserves_ac` derives target AC from source AC, equal capacity, and per-configuration load dominance, without a target-AC premise. The concrete trace theorem is also not a mere restatement: under its supplied simulation it derives durable/stable final bindings, injectivity, and the cross-operation sum bound. Complete mediation, attempt/event coverage, and the per-stable-ID aggregate outcome bound remain explicit external hypotheses.

## Frozen-matrix assessment

| Frozen theorem | Assessment |
|---|---|
| `checkAC_sound` | Pass: executable finite check implies semantic AC. |
| `guardClosure_iff` | Technical pass; principally the exact set-definition interface used by Prepare. |
| `simulation_preserves_ac` | Pass, conditional on the certificate's load-dominance premise. |
| `restriction_preserves_wf_ac` | Pass: computed target derives WF and AC. |
| `prepare_preserves_wf_ac` | Pass: exact guard, promotion, cleanup, and `PrepareOK` derive the target properties. |
| `ticket_step_preserves_wf_ac` | Pass: authority and stable bindings are preserved. |
| `step_preserves_wf_ac` | Mixed: computed/ticket cases pass; topology structural WF is supplied fieldwise by `TopologyShape`. |
| `trace_preserves_wf_ac` | Kernel pass over the current `Step`, inheriting its topology scope. |
| `effect_coverage` | Pass, with the per-operation aggregate outcome bound explicit. |
| `concrete_trace_authority_safety` | Conditional pass; not a deployed-runtime refinement. |

## Research value

The result is useful supporting evidence rather than dependency-only scaffolding: it machine-checks several derived transformations and temporal binding properties over arbitrary finite carrier types, not only the bounded Python instances. It is not decisive evidence for the paper's full RQ3 because the development omits canonical choice/parallel Fork, replace/live Restore, `Mono_0(pi)`, the `rho` transfer/fiber conditions, fresh fragment issuance, a general proof-object checker, and a dispatch-owning runtime adapter.

## Paper impact

The approved experiment plan says a mixed result must not enter the paper as a full mechanization claim. Accordingly, this step makes no paper change.

A later positive experiment may safely report a finite abstract submodel covering executable AC admission, exact restriction and Prepare/cleanup, ticket phases, and trace induction, while stating that topology and concrete trace results are conditional. It must not claim that the full checkpoint/fork/restore/merge lifecycle, complete mediation, aggregate sink bounds, or Claude/Codex safety have been verified.

## Priority findings and next decision

- **P0 for paper wording:** do not claim full lifecycle mechanization or a real runtime refinement from this result.
- **P1 scientific gap:** mechanize computed canonical Fork/Restore/Merge targets, monotone zero-preserving projections, transfer-map/fiber conservation, and checker soundness so target structural WF follows from source state plus checked operation data rather than a fieldwise logical certificate.
- **P1 systems gap:** validate complete mediation, binding capture, event coverage, and aggregate outcomes in one dispatch-owning adapter or mandatory proxy.
- **P2 liveness/modeling issue:** `restrictLifecycle` conservatively closes every branch identity outside the retained set, including unissued identities; this preserves safety but can prevent later fresh forks and should be repaired in the next lifecycle iteration.

**Decision:** retain the Lean development and raw evidence as an internal finite-submodel result, make no paper mechanization claim in this step, and admit a follow-up topology/checker experiment before promoting the result into the paper.
