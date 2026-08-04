# Round 0: Macro Structure

## Baseline and scope

- Entry semantic snapshot: `b903211d9cd7e93901ace07be86a7d7376f46fdc`.
- Entry HEAD: `9a17b6b0f3b8a5a8ed04e6bfa114aedd6ffa39e0`.
- During this round, an external commit advanced `main` and `origin/main` to `2c16570f0d26999df1f6a86ea71162d82dc0645b`; the rewrite preserved that state and did not run Git staging, commit, or push.
- Theory-paper adaptation: no evaluation RQs were introduced, following the author's explicit instruction.
- `Scope and Limitations` was not restored.

## Files reviewed

All LaTeX sources under `docs/paper/`, including the complete proof appendix, plus the current generated PDF.

## Major findings

1. The positive Fork, negative Fork, registered extension, two installation races, and the decisive prefix-unsafety counterexample were separated across Sections II and IV.
2. The checker appeared before an independently stated security objective.
3. Model, edit derivation, certificate machinery, and trusted-boundary material were combined in one dominant section.
4. The ideal and compiled runtime transition details obscured the main enforcement idea.
5. The central exactness result was not visually separated from supporting registration, lower-bound, repeated-use, and bisimulation results.
6. Registered extension had too much narrative weight for a supporting result.

## Changes applied

- Rebuilt Section II as `Execution-Edit Safety by Example` with:
  - `Accepted and Rejected Forks`;
  - `Prefix-Unsafe Outcomes`;
  - `Installation Races`.
- Added explicit Accept/Reject verdicts and concluded Section II with three requirements: outcome preservation, completion after every permitted prefix, and atomic installation.
- Renamed Section III to `Model and Security Objective` and stated the four declarative realization obligations before presenting the checker.
- Started Section IV at edit derivation, yielding the spine:
  `Model and Security Objective` -> `Exact Checking of Execution Edits`.
- Renamed Section V to `Runtime Enforcement`, retaining the canonical monitor and installation boundary in the body.
- Moved the ideal machine and detailed compiled state, invariant, guarded-call rule, installation premises, field updates, and transition bookkeeping to the proof appendix.
- Renamed Sections VI and VII to `Formal Guarantees` and `Mechanization and Executable Validation`.
- Kept AI Use Acknowledgment after the appendix and before references.

## Verification

- `latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex`: passed.
- Final log: no undefined references, undefined citations, or overfull boxes.
- Generated PDF: 23 pages, 519,803 bytes.
- Main narrative now ends on page 11; appendix material begins after the page break on page 13.
- `docs/paper/main.pdf` remains tracked and is not ignored.

## Remaining work

- Paragraph- and sentence-level flow, especially the dense model/checker proofs.
- Abstract and introduction rebuild.
- Separate the five theorem clauses into a ranked guarantee narrative without changing their formal meaning.
- Expand related-work positioning.
- Full terminology, citation, and meaning-preservation audits.
