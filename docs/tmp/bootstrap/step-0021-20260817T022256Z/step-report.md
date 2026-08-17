# Step 0021: Operation identity independent of Agent scheduling

Status: completed, 2026-08-17T02:50:07Z. Phase:
BUILD_AND_EVALUATE. Gate path: EXPERIMENT, light documentation update, REVIEW.

## EXPERIMENT

At entry, the root reread `docs/user-instruction.md`, the paper's restart and
runtime claims, `docs/evaluation.md`, and `docs/system-contract.md`. The selected
question was whether transparent recovery incorrectly depended on repeated MCP
RPC IDs and call order. This ranked above jailer integration or another VM
containment demo because it could invalidate every existing Agent recovery run.

The admitted plan is
`experiment-stable-operation-identity/plan.md`. The implementation added a
schema-2 operator configuration, stable Operation lookup from required tool
arguments, independent full-request conflict checking, RPC-neutral saved
responses, exact configuration binding, and schema-1 compatibility.

The reviewed result is
`experiment-stable-operation-identity/result-review.md`. Direct evidence:

- real Codex reorder and new-call-identity run:
  `experiment-stable-operation-identity/raw/`;
- official Claude after complete Firecracker VMM loss:
  `../s21-fc/raw/` from the bootstrap directory;
- independent checker passes for both runs and mutation rejection; and
- `make runtime-verify` passed, including race, vet, 114 Python tests, KVM
  integration evidence, and DeathStar microservices.

## Documentation update

No file under `docs/paper/` changed. The light update records only established
implementation facts in `docs/evaluation.md`, `docs/system-contract.md`,
`docs/mcp-continuity-runtime.md`, and `docs/firecracker-claude-runtime.md`.
It introduces no paper-level term beyond History, Requirement, Operation,
Rule, and Certificate.

## REVIEW and routing

The result supports RQ4 and removes deterministic transport replay as a hidden
deployment precondition. It does not close RQ4, prove complete mediation, or
justify a performance claim. No scientific-contract change or paper edit was
made. A fresh independent reviewer was unavailable because delegation was
prohibited for this run; raw systems evidence and independently implemented
checkers are the basis of the disposition.

Ranked open objections:

1. Only declared MCP tools are mediated; Claude/Codex built-ins and arbitrary
   process egress can bypass this frontend.
2. The operator still supplies the stable application field; the runtime does
   not infer Operation identity from text or packets.
3. Adoption is not yet a one-command launcher across process, container, and
   VM backends.
4. A maintained application and strongest deployment baselines remain needed.

Next route: a transparent launcher plus enforced service egress, evaluated on
one maintained application. Firecracker remains one optional containment
backend rather than the product boundary.
