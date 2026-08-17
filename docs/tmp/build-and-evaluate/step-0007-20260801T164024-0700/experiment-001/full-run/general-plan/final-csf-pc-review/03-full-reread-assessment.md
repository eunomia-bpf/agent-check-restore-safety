# Full-reread assessment

## Formal and paper alignment

I found no acceptance-critical proof-to-paper mismatch after rereading the
abstract, model, semantics, results, validation, related work, and limitations
against the Lean declarations.

- The generic theorem really has the stated limited scope: target current
  fibers for a computed child batch and unchanged initial token set.
- Full target safety uses additional source lifecycle, stable-binding, and
  transfer premises; the paper does not present the local atom as sufficient in
  isolation.
- The arbitrary-history result preserves a pre-existing logical binding, not
  physical exactly-once execution.
- The fixed-epoch projections and optional `WitnessCoherent` assumption are now
  accurately limited.
- Dynamic epochs, truthful operation/lineage classification, complete
  mediation, concurrency/storage refinement, and external reconciliation are
  all disclosed as assumptions or nonclaims.

The core is therefore conditionally correct. The rejection risk is that the
conditions and definitions make the main theorem too easy and move the hardest
agent problem outside the proof, not that the theorem is false.

## Trajectory evidence and ethics

The self-hosted paper-formation trajectory is not misused in the current text.
It is explicitly one author-operated retrospective case, not independent
samples; counts are rounded; copied log rows are not called duplicate effects;
no trace is labeled safe/unsafe; and no prevalence or correctness claim is
drawn. Public TraceLab and the private trajectory are used only for workload
shape and telemetry absence. This is scientifically weak evidence, but not a
fabricated or circular safety result.

The privacy section identifies incidental third-party text, minimizes emitted
fields, excludes prompts/commands/paths/stable identifiers, restricts access,
withholds private summaries from the anonymous artifact, and promises deletion
of research copies/key. No ethics desk-reject issue is apparent from the paper.
Because no core result depends on the private dataset, non-release is tolerable.

The accept-impact problem is evidentiary: a deliberately self-hosted workflow
shows that the authors can create branching history and that telemetry lacks
their newly defined fields, but it cannot show that real runtime behavior needs
eager occurrence transport or that the proposed `rho` can be trusted. It should
not be used to compensate for the missing separation theorem or native adapter.

## Cycle-level intent audit

The recorded user instructions ask for a large, nontrivial, principled result
that covers rich agent execution and connects to Claude/Codex. They are present
verbatim in `docs/user-instruction.md`, including the request to analyze the
paper-formation trajectory. However, `docs/idea-story.md` still records a
stronger frontier around correlated authority factorization and owner-order
serializability, whereas the submitted headline is now token-fiber equality
inside one fixed epoch. This does not create a PDF inconsistency, but it is a
real scientific narrowing relative to project intent and explains the
originality/significance risk.

