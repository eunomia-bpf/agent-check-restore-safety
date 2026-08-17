# Invocation 003 — static scans

Commands and results:

```text
rg -n '\b(sorry|admit|native_decide)\b|^[[:space:]]*axiom\b' \
  lean/AuthorityContinuity/PlanInvariantDrop.lean
=> no matches

rg -n 'hPfits|hbatchP|PrepareOK|targetValid|target_valid' \
  lean/AuthorityContinuity/PlanInvariantDrop.lean
=> no matches

git diff --check -- lean/AuthorityContinuity/PlanInvariantDrop.lean
=> exit 0, no output

sha256sum lean/AuthorityContinuity/PlanInvariantDrop.lean
=> e288da9813c8a22c2447e2a3b0fcb8109f9c62544f39dc2e22ce4885b11b0f67

wc -l -c lean/AuthorityContinuity/PlanInvariantDrop.lean
=> 552 lines, 23233 bytes
```

The source does contain ordinary English discussion of “target validity,” but
it contains no target-validity premise and no readiness oracle.
