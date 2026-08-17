# Invocation 004 — static scans and source identity

Results:

```text
sha256sum lean/AuthorityContinuity/PlanInvariantMerge.lean
=> 62aaecb14097912ee6824a94be6f38de5163993af650658acd2effb8d4f69477

sha256sum lean/AuthorityContinuity/PlanInvariantMergeExamples.lean
=> e5464e36c756598173bb9b0a4910ab38b4f6480509efb66ad932c2b222e00126

sha256sum lean/AuthorityContinuity/PlanInvariantGrammar.lean
=> 5f9553bd596b847ad440e76a12876b58929b24ee661a4245a3ab906dee832c2f

wc -l -c lean/AuthorityContinuity/PlanInvariantMerge.lean
=> 376 lines, 16935 bytes

wc -l -c lean/AuthorityContinuity/PlanInvariantMergeExamples.lean
=> 60 lines, 2664 bytes

wc -l -c lean/AuthorityContinuity/PlanInvariantGrammar.lean
=> 303 lines, 12923 bytes

git diff --check -- <all three files>
=> exit 0, no output

rg -n '\b(sorry|admit|native_decide)\b|^[[:space:]]*axiom\b' <all three files>
=> no matches

rg -n 'hPfits|hbatchP|PrepareOK|targetValid|target_valid|hTargetValid|hReady' \
  <all three files>
=> no matches
```

The Merge source explicitly states that its fixture result is not a claim
that all same-slot descriptors accept.
