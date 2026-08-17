# Semantic and premise audit of `AuthorityContinuity/Plan.lean`

## Verdict

**Overall verdict against the accepted Revision-2 headline gates: FAIL.**

**Verdict as a narrower supporting mechanization: MIXED.**  Invocation 005 is
valuable evidence that the actual checked transfer can compute a child batch,
that fiber demand gives per-root `B' <= B`, that the numerical update
`W' = W + (B-B')` preserves `B+E+W=P`, and that a checked assignment can be
projected to the repository's real `PrepareOK`/`prepareState`.  Those statements
are kernel checked and contain no direct target-`LWF`, target-`AC`, target
`PrepareOK`, or target-accounting premise.

They are not yet the reviewed plan-capability transport theorem.  The current
trace preserves only `ExactAccounting`; the missing invariants are precisely
the facts that would make an old plan authorize the next Prepare without
re-solving it.  Therefore invocation 005 must not be counted as positive
support for frozen gates 3 or 4, nor as the general positive result in the
paper.

## Gate-by-gate classification

| Accepted obligation | Result | Static evidence and consequence |
|---|---|---|
| Actual lifecycle projection | **PASS** | `PlannedStep.actual_step` projects canonical and Prepare constructors to the repository's `Step`; Prepare targets the exact `prepareState`. |
| Child batch computed from checked `rho` | **PASS** | `childBatch` is computed, and `computed_batch_load_le` / `computed_root_batch_load_le` use `Transfer.CoreValid.fiber_demand`; no caller supplies `U'`. |
| Exact selected-batch `B/E/W=P` update | **PASS, narrow** | `afterTransfer_exact` derives the natural-subtraction update after proving `B' <= B`; `afterPrepare_exact` moves the whole current root batch from `B` to `E`.  This is sound numerical accounting for the definitions present. |
| Zero-demand leaf visibility | **MIXED** | The `disposition` datatype makes categories exclusive and the transfer lemmas retain zero-demand children.  There is no validity invariant making the partial map total over every extant batch lineage or relating the three categories to live lifecycle phases. |
| Authoritative head/version CAS | **MIXED** | Canonical and Prepare constructors contain `checkHead`, and their computed targets increment `version`.  The cursor/head does not advance after Prepare, so this is a version guard around a single slot, not the accepted ordered residual plan. |
| Complete `PlanValid` | **FAIL** | There is no `PlanValid`.  `ExactAccounting` is only `B_i+E_i+W_i=P_i`.  It omits the durable baseline equation, all-live `L_i+E_i<=R_i`, `P_i<=R_i`, lifecycle/leaf alignment, owner purity, grant/epoch stability, ordered-fiber safety, and cursor correctness. |
| Computed root slot over all tentative claims | **FAIL** | `transferLeafRoot` computes through `rho` only for members of `childBatch tr p.remaining`; every non-batch target keeps its old target-ID entry.  A non-batch child with `rho c' = some c` therefore need not inherit the source root, contrary to the frozen equation for every current tentative claim. |
| Owner-group Prepare and cursor advance | **FAIL** | `headGroup` is the entire remaining batch at `currentSlot`, not one current owner group.  `afterPrepare` changes `version`, `disposition`, and `E`, but never changes `currentSlot`.  After a nonempty Prepare, `afterPrepare_remaining` makes that slot's head empty; later-slot leaves are stranded and another Prepare is blocked by `hne`.  Partial same-slot Prepare followed by refinement is unrepresentable. |
| `prepare_head_is_ok` derived from plan validity | **FAIL** | It does construct a real `PrepareOK`, but `htentative`, `hbatchP`, and especially `hPfits` are supplied anew.  `hPfits` is the load-bearing current-head readiness inequality, and together these premises reassemble the semantic/status and arithmetic parts of `PrepareOK` instead of deriving them from a transported `PlanValid`. |
| Positive grammar required by Revision 2 | **FAIL** | `PlannedStep` has checkpoint, canonical Fork/Restore, Prepare, and ticket steps only.  It has no computed restriction/Revoke-drop constructor and no checked same-slot Merge constructor.  The separate negative Merge example does not add either operation to this trace grammar. |
| Arbitrary-trace plan transport | **FAIL** | `planned_trace_preserves` concludes base lifecycle invariants plus `ExactAccounting` only.  It does not conclude complete plan validity, version/cursor monotonicity, stable bindings, residual schedule safety, or next-Prepare readiness.  Every Prepare edge already carries the crucial readiness premises, so the induction does not establish reusable authorization from the plan. |
| Forbidden target premises | **PASS literally; FAIL scientifically** | No constructor accepts target safety or target plan validity.  However, per-edge `htentative`/`hbatchP`/`hPfits` launder the missing source-plan invariant into nearly the exact facts needed for that one Prepare.  This avoids literal target circularity but weakens the claimed result in the way the frozen premise audit was intended to prevent. |
| Kernel/axiom status | **PASS** | Invocation 005 exits successfully.  Printed dependencies contain standard `propext`, `Classical.choice`, and `Quot.sound`, with no `sorryAx`.  Kernel success does not repair the semantic weakening above. |

## Decisive countermodels and failure arguments

### 1. `ExactAccounting` is far weaker than plan validity

Set every disposition to `none`, so `B=0`, and choose `E=P=1`, `W=0` for a
slot while setting `R=0`.  `ExactAccounting` holds, even though `P<=R` and
`L+E<=R` fail and `E` need not correspond to any durable promotion.  More
simply, with `B=E=W=P=0`, `ExactAccounting` holds for an arbitrary lifecycle,
root map, cursor, and leaf classification.  Thus the premise and conclusion of
`planned_trace_preserves` cannot imply any of the missing semantic invariants.

### 2. Prepare consumes the only representable head but does not select a next one

By definition,

```text
headGroup(p) = remaining(p) filtered at currentSlot(p).
remaining(afterPrepare p) = remaining(p) \\ headGroup(p).
currentSlot(afterPrepare p) = currentSlot(p).
```

Therefore the new head group at that same cursor is empty after every admitted
nonempty Prepare.  Since `PreparePlanned.mk` requires `headGroup.Nonempty`, a
second slot cannot be consumed.  This directly contradicts the accepted
atomic-head obligation to preserve the tail and advance to the first nonempty
remaining slot.

### 3. The trace theorem assumes the interesting scheduling fact per edge

`PreparePlanned.mk` asks for

```text
durableLoad(current lifecycle) + P(currentSlot) <= capacity.
```

That premise is then used verbatim as the final step in constructing
`PrepareOK.base`.  The absent durable-baseline, `L/R`, and order invariants do
no work.  Consequently, the theorem says: if each future Prepare is separately
shown ready, then a trace of separately-ready Prepare steps stays safe.  It
does not say that the original checked plan remains sufficient after
Fork/Restore.

### 4. The root map does not cover the resource envelope

The reviewed plan charges *all* tentative descendants of a scheduled owner to
`R_i`, including non-batch claims.  Current `leafRoot` is updated through
`rho` only when the target claim belongs to the selected child batch.  For a
non-batch source claim `c` and target `c'` with `rho c' = some c`, the intended
root is `root(c)`, but current `transferLeafRoot` returns the pre-existing
target-ID value `leafRoot(c')`.  Thus an owner-purity or `L_i` theorem cannot be
derived from this map, and `R` is semantically dead data in the module.

## What is sound and should be retained

1. Retain the arbitrary-batch fiber summation and per-root conservation
   lemmas.  They are the correct bridge from the actual transfer checker.
2. Retain the computed `childBatch` and the narrow `B/E/W=P` transfer and
   Prepare algebra, but describe it as one field of plan validity rather than
   plan validity itself.
3. Retain the finite assignment checker and the exact projection to
   `PrepareOK`; its assignment fields are honestly derived from executable
   checks.
4. Retain the real `Step` projection and standard-axiom audit.

## Minimum repair needed before a positive headline classification

1. Add ordered finite slots (or a cursor into an ordered slot list), a durable
   baseline `d0`, and an explicit exhausted state.  Define `advance` as the
   first slot with a nonempty remaining leaf set; make `afterPrepare` compute
   it atomically.
2. Separate the all-tentative `rootSlot` map used for `L/R` and owner purity
   from the per-lineage leaf ledger if necessary.  Compute the former through
   `rho` for every target tentative claim, not only selected-batch children.
3. Define a genuine `PlanValid A p` containing at least durable-load equality,
   `L+E<=R`, `B+E+W=P`, `P<=R`, total/exclusive leaf/lifecycle alignment,
   computed owner purity, stable grant/epoch facts, source order safety, and
   cursor-first-nonempty correctness.
4. Replace `htentative` and `hbatchP` in `PreparePlanned.mk` by derivations from
   `PlanValid`.  Derive the capacity bound from the durable baseline plus the
   residual slot/order invariant; do not accept `hPfits` as a fresh edge
   premise.
5. Make the head one actual owner group within a slot, or explicitly weaken
   the paper and reviewed theorem away from partial same-slot Prepare.  The
   current whole-slot group cannot support the frozen multi-round history.
6. Add computed restriction/Revoke-drop and checked same-slot Merge to the
   positive grammar, with preservation of full `PlanValid`; keep cross-slot
   Merge outside that grammar as the negative witness.
7. Strengthen the trace conclusion to full `PlanValid`, cursor/version
   monotonicity, stable post-Prepare binding, and next-head readiness.  Only
   then does the induction establish transport of a capability rather than
   preservation of an accounting identity.

## Paper-facing disposition

Until those repairs kernel-check, the defensible claim is:

> We mechanized computed selected-batch lineage accounting and an exact
> Prepare-to-ticket bridge over the real lifecycle semantics.

The following stronger claim is **not supported by invocation 005**:

> An already checked multi-slot promotion plan remains a sufficient linear
> capability across arbitrary admitted Fork/Restore/Prepare histories.

