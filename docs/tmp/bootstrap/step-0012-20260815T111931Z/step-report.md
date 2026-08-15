# Step 0012: independently check every Certificate

Date: 2026-08-15 UTC

## Outcome

The runtime no longer trusts its Rule compiler alone. A new standalone checker
accepts only a compact, versioned History projection and a Certificate, rebuilds
the bounded decision with a separate search implementation, and rejects any
different Rule or impossible decision. Its production package imports only the
Go standard library.

The control service invokes the independent checker before returning a
Certificate, again while activating it under the History lock, and again while
replaying a recorded activation. The compiler uses recursive search; the
checker uses an explicit stack over independently decoded wire types.

## Real process run

An actual control process performed these steps over HTTP:

1. compile a Requirement containing one useful and one resource-consuming
   Operation kind;
2. export the answer-preserving History projection;
3. check the Certificate in the standalone command;
4. activate the checked Rule;
5. stop the complete control process; and
6. start a new process over the same History and head anchor.

The standalone verdict was:

```json
{
  "valid": true,
  "decision": "activate",
  "history_sequence": 0,
  "history_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "rule_version": 1
}
```

State immediately after activation and state reconstructed after restart have
the same SHA-256 digest:

```text
87b9e7e774cc56dcc1c712011d8febc490f22a72448d5c48363b936463995193
```

The retained directory includes the Requirement, Certificate, compact
projection, checker verdict, binary History, authenticated head anchor, and
both state snapshots. No credential is retained.

## Boundary failures fixed

The checker was changed after an independent audit found three material gaps:

- its first search order could reject a valid Certificate after hitting the
  state limit even when the compiler succeeded;
- accepting the complete runtime State made the public 16 MiB limit reject a
  semantically tiny decision; and
- irrelevant result and resource dimensions could multiply across all open
  Operation outcomes and exhaust memory.

The final design uses the same bounded canonical branch order through a
different explicit-stack implementation, a compact answer-preserving
projection, saturated target result counters, exact 64-bit resource use, and
only target dimensions. Recursive duplicate JSON keys are rejected. A
regression with a full State above 16 MiB produces a projection below 1 MiB
and checks successfully. Another regression exercises 16 kinds at the search
boundary. Determinism tests repeat compiler and checker cases 20 times.

## Formal semantic layer

`lean/AuthorityContinuity/RuntimeCertificate.lean` independently defines
finite History worlds, bounded Requirement completion, the canonical largest
Rule, and activate/impossible Certificate correctness. Eight theorems establish
that every member of the canonical Rule is safe, every safe candidate Rule is
a subset of it, the executable semantic verifier is exact, and activate and
impossible decisions cannot both be correct. The repository audit checks the
theorems for placeholders and non-whitelisted axioms.

## Verification

```sh
make runtime-verify
cd runtime
go test -count=20 ./internal/kernel ./internal/certcheck
go list -deps ./cmd/check-certificate
cd ../lean
./scripts/audit.sh
```

`runtime-verify` passed the full Go build, race suite, and vet. The dependency
list contains none of the compiler, control, History, or gateway packages.

## Honest boundary

The online path derives the projection while holding the control lock and
compares it with the current authenticated History point. The standalone
command cannot establish the provenance of a caller-supplied projection; an
external verifier must compare its History point with a trusted head anchor.

The Lean proofs cover the finite semantic model, not yet the Go projection,
strict JSON decoder, SHA-256 binding, or numeric-limit correspondence. Schema 1
also signs a human-readable rejection reason rather than a structured proof
object. These are explicit refinement tasks, so this milestone is an
independently checked bounded runtime, not yet proof-carrying execution.

No file under `docs/paper/` changed in this step.
