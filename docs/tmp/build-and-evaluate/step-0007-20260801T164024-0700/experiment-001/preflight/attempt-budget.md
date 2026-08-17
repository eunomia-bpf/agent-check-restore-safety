# Retained Lean preflight attempt budget

- Accepted plan: `../plan.md`, revision 2.
- Independent authorization: `../plan-review-r2.md`, verdict `ACCEPT`.
- Repository base: `dd5ad7cefaaabf54ad59e9743e3e66f891bab703`.
- Pinned toolchain: Lean and Mathlib `v4.30.0`.
- Maximum real preflight attempts: **3**.
- Attempts used before source installation: **0**.
- One attempt is one retained invocation of the command below against one
  hashed source snapshot; no auxiliary Lean/editor elaboration command is
  permitted outside that count.

```sh
cd /home/yunwei37/workspace/my-paper-work/agent-check-restore-safety/lean
lake build AuthorityContinuity
```

| Attempt | Source snapshot | Command log | Exit | Status |
|---:|---|---|---:|---|
| 1 | `b8161ba8df2a853df240a23c3fa78a30ea8a5b1cb95488e19583bbfce856689f` | `attempt-1.log` | 127 | failed: `lake` absent from shell `PATH`; no elaboration |
| 2 | `b8161ba8df2a853df240a23c3fa78a30ea8a5b1cb95488e19583bbfce856689f` | `attempt-2.log` | 1 | failed: four dependent-pattern arities in `PlannedStep.actual_step`; native-decision axioms exposed |
| 3 | `ce87238a31079b79f1bc78735f8e68c5be4d29ea702dc11ac09e1214fa38a029` | `attempt-3.log` | 0 | **passed**: 756 jobs; five requested theorem axiom reports contain only the repository allowlist |

Static source reading, plan review, and candidate drafting outside the Lake
source glob do not consume an attempt.  No paper, canonical design/evaluation,
idea-story, or user-instruction file may be edited until independent result
review.

Attempt 2 keeps the exact source and build target from Attempt 1.  Its shell
environment prepends the already installed pinned binary directory
`/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin` to `PATH`, as
required by `lean/README.md`; no repository source or dependency changes.
