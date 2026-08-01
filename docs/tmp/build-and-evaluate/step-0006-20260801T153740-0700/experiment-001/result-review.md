# Experiment 001 result review: failed Boundary II Lean preflight

Review date: 2026-08-01 (America/Vancouver)

Scope: independent review of the approved Experiment-001 preflight. No fourth build was run, and no Lean, paper, or canonical evaluation file was edited.

## Verdict

~~~text
headline classification: inconclusive
run status: incomplete
tested hypothesis: inconclusive
research value: dependency-only
paper impact: no new RQ2 evidence and no claim update
artifact status: invalid as proof evidence
failure class: environment on attempt 1; proof engineering on attempts 2–3
theorem counterevidence: none
circularity found: none
~~~

This is not a negative result about Boundary II. Lean produced no counterexample, failed implication, or contradictory well-formed authority state. The third attempt stopped because the draft asked native_decide to synthesize Decidable instances for quantified Prop obligations and did not supply constructive proofs. That is an elaboration/proof-engineering failure.

It is also not a mixed scientific result. Some declarations were elaborated far enough for axiom reports to print, but the module exited nonzero, no Serialization.olean exists, and the real-step declarations contain synthetic sorryAx dependencies. Partial elaboration cannot count as positive evidence.

Experiment-001 therefore stops at preflight. Its general iff, authority instantiation, assumption mutations, audit, kernel replay, and cross-check were not run.

## Material and integrity

Reviewed:

- the approved plan and accepted plan review;
- the current lean/AuthorityContinuity/Serialization.lean;
- all three preflight logs;
- RQ2 and the mechanization/stop rules in docs/evaluation.md;
- the complete Step 0006 Lean design report;
- the Lake submodule glob and audit script.

Hashes:

| Artifact | SHA-256 |
|---|---|
| Serialization.lean | bb25e8fa5f47576da00511a734c55b2c5db241b1115f4f0ff404f9884b535faa |
| attempt 1 | a867b2941e105dad50fedc482873bb493078314df1039d9daaba979191dfc0f9 |
| attempt 2 | 821465d9535f23ae3cdb44f04f8f372baac52b4c6a4f382983833c7e8c766b4a |
| attempt 3 | 15a542b2cf8d302a3483213e4b8dc5644928b5dfa716bfaa270d563594062959 |

The current source is the source used by attempt 3: its modification time precedes that log and every diagnostic line matches.

## Attempt classification

| Attempt | Terminal observation | Classification |
|---|---|---|
| 1 | lake: command not found | environment/path failure |
| 2 | pinned Lean reached Serialization, then failed on declaration-name shadowing and resulting type/elaboration errors | proof engineering |
| 3 | pinned toolchain reached Serialization, then fifteen finite quantified obligations lacked synthesized Decidable instances | proof engineering |

Attempt 1 does not make the final outcome environment-only. Attempts 2 and 3 show that the pinned toolchain and repository dependencies ran. The terminal blocker was the proof construction.

The third-attempt failures cover downward closure and grant-open fields of source LWF, ActiveExact, and the positive/unsupported PrepareOK declarations. Every diagnostic is inability to synthesize Decidable for a proposition; none says the proposition is false.

## Why the printed names are not evidence

Lean continued after errors using synthetic placeholders so it could emit more diagnostics. The resulting axiom output is not a successful audit:

- Positive.order_ab_real_steps contains sorryAx;
- Positive.order_ba_real_steps contains sorryAx;
- Unsupported.order_ts_real_steps contains sorryAx;
- the process ends with Lean exited with code 1 and build failed;
- no Serialization.olean was produced.

The source contains no literal sorry, admit, project axiom, or constant, but that is insufficient: failed elaboration inserted sorryAx into the attempted declarations. Cherry-picking later printed equalities is invalid because the containing module did not build and the approved gate requires one successful module plus a clean dependency audit.

## Theorem and circularity assessment

### No theorem counterevidence

There is no model counterexample and no disagreement with the existing Python witness. The correct interpretation is:

> The preflight did not test the theorem to completion; it neither supports nor contradicts Boundary II.

### No circularity found

The draft has the intended non-circular shape:

- owner groups are frozen from the source state and batch;
- per-group assignments restrict the original stable assignment;
- intended edges use the existing PrepareOK and CoreStep.prepare;
- final support reads only the atomic guarded family;
- authority equality is a separate conclusion;
- the unsupported path uses actual terminalization and failure of PrepareOK.member_open;
- the file does not define or assume the general Boundary II theorem.

PrepareOK contains neither final support nor atomic equality. This is a good design diagnostic, not a proof result.

## Completion audit

| Approved requirement | Status |
|---|---|
| real pinned two-owner preflight | failed after three attempts |
| both positive orders through real CoreStep.prepare | not established |
| unsupported example with one success and one disabled order | not established |
| clean lake build AuthorityContinuity | failed |
| whitelist-clean axiom report | failed |
| general finite-carrier iff and authority instantiation | not started |
| assumption mutation suite | not started |
| audit.sh, leanchecker, and Python regression | not run |

The separately completed closest-work map remains usable: it narrows the possible novelty to the authority-specific final-support closed form. It cannot turn this failed preflight into a mixed or positive result.

## Artifact disposition

Keeping the uncompiled file at lean/AuthorityContinuity/Serialization.lean is not acceptable.

The Lake library uses a submodules glob for AuthorityContinuity. Consequently every Lean file below that directory, even an untracked one, is included by lake build AuthorityContinuity. The failed draft therefore breaks the authoritative library merely by remaining at that path and looks like a proof module although none of its preflight claims exists in a successful compiled artifact.

Acceptable forensic preservation is:

1. preserve the exact failed source, hash, and logs under the experiment directory, preferably with a suffix such as .lean.txt that Lake cannot discover;
2. remove it from lean/AuthorityContinuity so the previously validated library can build again;
3. restore an authoritative Serialization module only after a clean build and axiom audit.

This review does not perform that relocation because Lean edits are out of scope.

## Claim decision

No scientific claim may be added or strengthened from this preflight. In particular, the project may not say that:

- Boundary II is mechanized;
- either fixed example kernel-checks;
- all owner orders were verified in Lean;
- serial and atomic authority states were proved equal in a built module;
- the module is axiom-clean; or
- the failure supplies evidence against the theorem.

The existing evaluation rule remains controlling: Boundary II is a paper proof, and Python supplies only bounded executable validation.

Internal reporting may state only that the three-attempt preflight closed inconclusively, the final blocker was proof engineering, no circular premise or theorem counterexample was found, and Boundary II remains outside the successful Lean scope.

## Exact next decision

1. Close Experiment-001 as inconclusive. Do not run attempt 4 and do not proceed to its general-theorem/full-run stage.
2. Restore the authoritative build by relocating/removing the failed draft from the Lake glob. This is repository hygiene, not research evidence.
3. Do not open another experiment merely to try the same file again. Compilation repair alone is dependency work.
4. If Boundary II remains the decisive theory claim and sufficient budget exists, admit one materially revised general-mechanization experiment:
   - prove finite LWF, ActiveExact, and PrepareOK obligations constructively or derive them from Boolean checks with proved soundness;
   - keep native_decide controls separate from theorem dependencies, following the existing audit design;
   - retain actual PrepareOK/CoreStep.prepare enabledness and a whitelist-clean axiom report;
   - target the general authority-native normalization and iff, not another standalone fixed-example success.
5. If the full general theorem and audit cannot be funded, stop mechanization for this submission: retain Boundary II as explicitly unmechanized, narrow its novelty using the completed closest-work map, and move the research frontier to existential safe-order/minimal-coordination synthesis rather than accumulating finite examples.

Immediate paper decision: no claim change.

## Bottom line

The draft chose the right semantic objects and avoided circularity, but it failed the executable gate. Boundary II remains plausible and unmechanized; Experiment-001 produced proof-engineering diagnostics, not valid RQ2 evidence.
