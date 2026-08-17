# Scoped wording re-sign for the paper-formation trace

Date: 2026-08-02 (America/Vancouver)

## Verdict

**PASS for the exact `validation.tex` bytes pinned below.**

The current wording uses the self-hosted paper-formation lineage only to
describe a single retrospective workload, its extraction provenance, and the
shape and limitations of observed telemetry.  It does not use that case to
estimate prevalence, infer causality, label an execution safe or unsafe, or
support correctness of the formal model, reference monitor, agent runtime, or
external effects.

The wording does make narrow, test-backed statements about the extractor's
input boundary, deterministic output on unchanged input, accounting, and
privacy schema.  Those are provenance and method-integrity statements, not an
agent- or algorithm-correctness claim.  The paper makes this distinction
explicit by assigning security claims to Lean and implementation claims to
controlled tests, while saying that the trace gives no correctness evidence.

## Reviewed pin

```text
file    docs/paper/sections/validation.tex
sha256  8623cffef9e1886b3077f94597a137bd043a0fafb4b6f78afa42f105a79f4ccb
```

This verdict is byte-scoped.  Any subsequent change to `validation.tex`
invalidates the re-sign and requires another wording check.

## Claim-boundary audit

| Current wording | Admitted interpretation | Excluded interpretation |
|---|---|---|
| Lines 4--16 separate Lean, runtime tests, and traces and say no trace is labeled safe or unsafe. | Traces answer workload-shape and telemetry-observability questions. | Trace-based safety or algorithm correctness. |
| Lines 103--111 call the material one self-hosted, author-operated longitudinal dataset and retrospective case, explicitly not independent child samples, and round the counts. | One-case workload and lineage shape. | Population sampling or prevalence across tasks, projects, users, or runtimes. |
| Lines 106--118 state the cutoff, source pin, immutable-byte processing, validation checks, unchanged-input determinism, and adversarial-fixture coverage. | Extraction provenance and tested method-integrity boundaries. | Proof that the agent/runtime or proposed safety mechanism is correct. |
| Lines 120--127 report branching, inherited history, compaction, lifecycle records, workspace mutation, call/result correlation, and absent joint admission fields. | Shapes observed in this analyzed case and limits of its persisted schema. | Semantic Restore, duplicate effects, authority violations, or product-wide telemetry absence. |
| Lines 128--129 say the case motivates telemetry and fixtures but gives no unsafe-restore rate or correctness evidence. | Motivation and observability only. | Safety rate, efficacy, or correctness. |
| Lines 131--134 bound Claude evidence to a selected historical index and report no Claude tool/effect counts. | Bounded provenance and non-observation statement. | Exhaustive Claude absence claim or Claude/Codex equivalence. |

No causal claim appears in the scoped section: it reports observed records and
schema fields, but makes no counterfactual, treatment-effect, productivity, or
quality inference about multi-agent paper formation.

## Synthetic/adversarial regression

Executed from `private-paper-traces/`:

```text
python3 -m unittest -v \
  test_extract_private_paper_traces.py \
  recheck/test_recheck_adversarial.py \
  recheck-v3/test_recheck_v3_adversarial.py
```

Result:

```text
23 maintained tests + 16 prior recheck attacks + 21 v3 attacks = 60 tests
Ran 60 tests in 2.778s
OK
exit status 0
```

The prior attack suite was run from the required
`recheck/test_recheck_adversarial.py` path.  These tests exercise synthetic
fixtures and package-level integrity assertions.  They do not turn the
observational case into security or correctness evidence.

## Evidence and access boundary

- Read the current paper wording and synthetic/adversarial test sources.
- Running the tests imported the current extractor and exercised temporary
  synthetic files; package-level aggregate/replay assertions ran as already
  encoded in the suite.
- Did not open or inspect any raw private rollout, private SQLite source,
  prompt, command, result body, root/key input, or raw Claude action corpus.
- Did not run real extraction or regenerate private aggregates.
- Did not edit the paper, extractor, tests, or any other project source.
- Wrote only this scoped report and its sanitized companion log under
  `private-paper-traces/recheck-v3/`.

This re-sign supports only the wording boundary above.  Formal proofs and
controlled monitor tests remain responsible for security and implementation
claims.
