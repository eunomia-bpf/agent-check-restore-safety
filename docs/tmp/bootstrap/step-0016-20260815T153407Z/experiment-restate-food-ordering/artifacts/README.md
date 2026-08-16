# RQ4 raw evidence archive

`raw-evidence-20260816.tar.zst` is a deterministic archive of the complete
`raw/` directory after the Restate and Temporal food-ordering experiment. It
contains successful runs, failed preflight attempts, build provenance, raw
workflow histories, provider records, container inspections, checker outputs,
mutation results, and the final 55-lane Temporal parity matrix.

Archive facts:

- uncompressed tar bytes: `468756480`
- compressed bytes: `13154398`
- archive entries: `25539` (`22844` regular source files plus directories)
- unsafe absolute or parent-traversal paths: `0`
- Temporal full-matrix root:
  `raw/temporal-full-parity-full-20260816-v1/`
- Temporal full-matrix result: `55/55` lanes, `exit-status.txt = 0`
- Temporal full-matrix recursive checksum entries: `5680`

Verify the archive and list its contents from this directory:

```sh
sha256sum --check SHA256SUMS
zstd --test raw-evidence-20260816.tar.zst
tar --zstd -tf raw-evidence-20260816.tar.zst
```

The archive preserves the evidence; it is not a substitute for rerunning the
checkers in `runtime/deploy/restate/`, `runtime/deploy/temporal/`, and
`runtime/deploy/temporal-unsafe/`.
