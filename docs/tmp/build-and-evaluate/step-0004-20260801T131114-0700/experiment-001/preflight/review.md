# Preflight review

**Attempt:** 001 (accepted; no retry)

**Command:**

```text
python -m adapter.codex_litmus --suite adapter/litmus.yaml --runtime-lock adapter/runtime-lock.json --raw-dir docs/tmp/build-and-evaluate/step-0004-20260801T131114-0700/experiment-001/preflight/attempt-001 --output docs/tmp/build-and-evaluate/step-0004-20260801T131114-0700/experiment-001/preflight/attempt-001-summary.json --workspace . --preflight-only
```

**Admission verdict:** PASS. Proceed to the frozen 80-run matrix.

- The pinned real `codex app-server --stdio` emitted one client-owned
  `item/tool/call` with `callId=preflight-call-1`.
- The initial controller worker was hard-killed with exit status `-9` after
  the sink had one durable outcome and while the controller ticket remained
  `inflight`.
- Recovery used a different process, queried the sink, appended settlement,
  and returned the matching controller receipt.
- The final audit contains one sink attempt, one aggregate outcome, and one
  settled controller receipt.  It contains no redispatch after remote success.
- The App Server/frontend stayed alive and completed the original pending
  callback.  This preflight does not test App Server or frontend death.

Raw JSON-RPC, both SQLite durability domains, worker exit metadata, and the
machine-readable result are retained in `attempt-001/`.
