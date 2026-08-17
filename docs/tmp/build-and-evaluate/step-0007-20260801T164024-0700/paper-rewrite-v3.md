# Paper rewrite v3: typed history admission

This is the unattended rewrite outline required before restructuring multiple
paper sections.  The current token/promotion-plan draft is not the source of
the new headline claim; the mechanized typed-admission, durable-prefix, and
controller-cover modules plus the certifying artifact are.

## Fixed story

An agent history operation does not merely restore a workspace.  It preserves
an immutable durable past while changing a correlated set of future protected
effects.  A safe boundary must therefore answer two independent questions:

1. Which target handles denote the same atomic redemption cell?
2. Which gate uses share the controller state that enforces correlations among
   multiple cells?

The six typed operations derive `Candidate` and `Required`.  The durable prefix
and lineage derive the greatest fixed-candidate `Admitted` family.  Declared
co-live local controllers derive `RawPhysical`.  The offline structural check
is `Required <= RawPhysical <= Admitted`; actual deployment additionally owes
`Required <= Actual <= RawPhysical`.

## Section architecture

1. **Introduction**: workload shift; one running counterexample progressing
   from duplicate redemption to U(2,3) correlation cut; thesis; contributions;
   evidence and non-claims.
2. **Problem and boundary**: why snapshot state is incomplete; six lifecycle
   operations; immutable receipts; two independent quotients; trusted inputs
   and runtime refinement obligations.
3. **Model**: cells, authority atoms, downward-closed future families, durable
   prefix, typed `Candidate/Required`, greatest admitted residual, controller
   access/local families/co-liveness, `RawPhysical`, `Actual`, readiness.
4. **Typed admission semantics**: union/tensor operator rules; structural
   inheritance versus full readmission; four semantic outcomes; versioned
   composition; receipt growth.
5. **Controller realization and theorems**: readiness iff; support/minimal-
   nonface obstructions; per-cover `OutsideSupport/LocalOverpermission/
   CorrelationCut`; GateCut; functional partition reduction; actual prefix
   certificate transport; operational redemption substrate.
6. **Compiler and independent verifier**: strict manifest; normalization;
   synthesis pipeline; certificate/witness schema; structural seal only;
   finite caps and failure behavior.
7. **Evaluation**: Lean replay; compiler/verifier tests and exhaustive oracle;
   litmus suite; public/private Claude/Codex traces only for workload and
   adapter observability; small feasibility timing if available.
8. **Related work**: compare claim boundaries, not feature inventories:
   checkpoint/rollback, transaction/saga, idempotency, capability/linearity,
   event structures, supervisory control/security automata, agent-specific
   fences/reference monitors, proof-carrying authorization.
9. **Discussion/conclusion**: manifest-relative nature, product abstraction,
   missing parser/refinement proof, no effect authorization/external exactly-
   once, extension to workflow/RL/search runtimes.

## Moves and cuts

- Keep token linearity, Prepare/retry receipts, and the operational commitment
  LTS only as supporting lemmas or appendix material.
- Remove cache observation and SQLite/Codex callback as headline results; keep
  only if needed as small adapter evidence.
- Do not equate controller occurrences with redemption cells.
- Do not say every bad manifest has one unique root cause; the three labels are
  exclusive for a chosen deterministic cover.
- Do not claim Python is extracted from or refined by Lean.
- Do not claim a unique finest arbitrary overlapping cover.  The uniqueness
  theorem applies to the functional partition case.
- Do not mechanize or claim GateClone provenance in Lean; origin metadata only
  distinguishes the executable subtype.

## Contribution claims to preserve

1. Typed Fork/Restore/Merge admission derives correlated may/required futures
   and a fixed-frontier four-way semantic decision.
2. Durable-prefix transport computes the greatest safe residual within the
   supplied candidate and supports compositional structural inheritance.
3. Independent cell/controller identities plus controller realization yield a
   manifest-relative readiness theorem and minimal, typed failure evidence.
4. A small untrusted compiler and independent verifier reconstruct the finite
   decision and emit a non-authorizing structural seal.

## Evidence gaps routed to evaluation

- Real trace extraction must establish only prevalence/observability of typed
  lifecycle events, durable external actions, alias clues, and controller
  identity/co-liveness gaps.
- No trace statistic can prove `Actual` refinement or safety prevalence.
- Add measured compiler/verifier scaling only after running it; never invent
  numbers.
- Closest-work claims require primary-source citations and conservative wording.

## Abstract/introduction mapping diagnosis

The previous opening belongs to the superseded token/promotion-plan paper and
cannot be repaired by local wording changes.  Its paragraph roles map as
follows:

| Old intro paragraph | Current role | Target action and body source |
|---|---|---|
| 1: zero-demand copied approval | problem example | replace with a typed history edge whose individual cells are safe but whose co-live controller product realizes the forbidden U(2,3) triple (`lifecycle`, `results`) |
| 2: history-transforming agents and recent runtimes | mixed background/problem/prior work | split into background and existing-solutions paragraphs (`lifecycle`, `related`) |
| 3: three rollback domains | root cause | generalize to durable past, correlated future, controller realization, and external reality (`lifecycle`, `model`) |
| 4: ``history may be copied; authority occurrences may not'' | superseded insight | replace with two independent identities plus typed future admission (`model`, `results`) |
| 5: Prepare as linearization point | superseded system paragraph | demote to the durable-prefix substrate; introduce the certifying history-admission compiler (`algorithm`) |
| 6: token/cardinality accounting | superseded challenge/related work | cut from the opening; configuration families and controller products now explain the nontrivial challenge (`model`, `results`) |
| 7: contributions | stale contributions | replace with typed semantics, controller-cover theorem, and compiler/evidence deliverables (`results`, `algorithm`, `validation`) |
| 8: assumptions | limitations | retain only the current manifest/runtime/refinement boundaries after contributions (`lifecycle`, `discussion`) |

The target introduction uses seven roles in causal order: (1) background on
history-transforming computation; (2) concrete problem; (3) structural root
cause; (4) why snapshot, per-effect authorization, capabilities, and general
history-sensitive monitors do not decide this boundary; (5) the two-identity
insight; (6) the history-admission compiler and theorem/evidence summary; and
(7) concrete contributions.  A separate challenges paragraph is unnecessary:
the root-cause and existing-solutions paragraphs already expose the two
technical obstacles that the model answers.

The old abstract similarly begins with background but then consists almost
entirely of superseded promotion-plan/token claims.  The replacement will be
derived from the rewritten introduction in the same role order and will use
only theorem and evaluation claims already present in the body.
