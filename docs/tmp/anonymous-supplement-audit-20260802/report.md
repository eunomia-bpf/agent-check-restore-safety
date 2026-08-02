# Anonymous supplement audit

## Scope

The prior twelve-file command omitted the Lean development and bounded scaling
driver while the paper claimed both evidence layers.  The replacement uses an
explicit 52-file manifest containing:

- the compiler, independent verifier, 55 private-data-free tests, and one JSON
  fixture;
- the bounded scaling driver, but not the historical result JSON or timings;
- every Lean source required by the library, pinned Lake/Lean metadata, and the
  audit driver.

It excludes repository history, `docs`, downloaded papers, private trajectory
code and output, historical scaling JSON, Lean results/build output, caches,
and bytecode.

## Packaging checks

`artifact/build_anonymous_supplement.py` reads only explicit regular-file
entries.  It rejects absolute or parent paths, globs, symlinks, missing files,
known repository commits, repository author/committer identities, and fixed
local identity/path fragments.  Tar order, mtime, ownership, modes, USTAR
format, and the gzip header are normalized.

Two builds after the final included-source edits were byte-identical:

- files: 52;
- SHA-256: `5477114622433074a9a2b9f53de77f3907cb1a63f9fbdd0e5879eaa0453763bf`.

The digest is diagnostic rather than frozen because any included source edit
correctly changes it.

## Extracted-archive replay

From a fresh temporary extraction:

- `python3 -m unittest -v`: 55/55 pass;
- `python3 bench_history_admission_scaling.py --output /tmp/...`: pass and
  regenerate the deterministic counts/fail-closed fields.

The Lean sources were already built and axiom-audited in the source tree.  The
supplement README instructs reviewers to fetch the pinned Mathlib cache, build
the complete library, and run `scripts/audit.sh`; generated logs are not
shipped.
