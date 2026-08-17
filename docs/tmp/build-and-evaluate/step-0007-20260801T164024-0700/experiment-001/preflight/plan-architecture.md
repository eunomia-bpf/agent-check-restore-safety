# Step 0007 preflight: minimal Lean architecture

## Decision

Use the existing **replacing-Restore** fixture, not the parallel-Fork fixture,
for the first real invocation.  `TopologyExamples.replaceTransfer` computes one
child claim and the existing `Operation := Fin 1` can therefore cover the whole
computed child batch.  Parallel Fork computes two child claims and would force
an unrelated expansion of the operation carrier before testing the intended
vertical path.

The preflight should add one small module importing
`AuthorityContinuity.Step` and `AuthorityContinuity.TopologyExamples`.  It
should not attempt the general block theorem, ledger accounting, same-slot
Merge, or a trace closure.  Its one job is to connect these existing objects:

```text
checked replacing Restore
  -> rho-computed root and child batch
  -> one R/P fiber bound from Transfer.CoreValid.fiber_demand
  -> authoritative version check + finite assignment check
  -> actual PrepareOK and exact prepareState
  -> head consumed/version advanced
  -> actual Revoke, with the now-empty plan stuttering
  -> actual TicketStep.dispatch, with no old-plan check
```

## Minimal data (and nothing stronger)

The following is the complete proposed preflight data layer.  `R` and `P` are
data, not propositions.  There is no target invariant, `PrepareOK`, safe order,
or caller-provided child map in either structure.

```lean
structure PlanHead (Coord Claim Slot : Type*) where
  version : Nat
  currentSlot : Slot
  batch : Finset Claim
  rootSlot : Claim -> Option Slot
  R : Slot -> Coord -> Nat
  P : Slot -> Coord -> Nat

structure ControllerState
    (Coord Claim Branch Grant Operation Slot : Type*) where
  lifecycle : LifecycleState Coord Claim Branch Grant Operation
  plan : PlanHead Coord Claim Slot
```

For the thin one-head preflight, consuming the head clears exactly its current
batch and increments the authoritative version.  Do not add a general cursor,
prepared/withdrawn ledger, or multi-slot tail until this path compiles.

```lean
def PlanHead.advance [DecidableEq Claim]
    (p : PlanHead Coord Claim Slot) : PlanHead Coord Claim Slot :=
  { p with
    version := p.version + 1
    batch := empty
    rootSlot := fun c => if c in p.batch then none else p.rootSlot c }

def preparedController [DecidableEq Claim]
    (S : ControllerState Coord Claim Branch Grant Operation Slot)
    (assignment : Operation -> Option Claim) :
    ControllerState Coord Claim Branch Grant Operation Slot where
  lifecycle := LifecycleState.prepareState S.lifecycle S.plan.batch assignment
  plan := S.plan.advance
```

Expected definitional/simp lemmas:

```lean
@[simp] theorem preparedController_lifecycle :
    (preparedController S assignment).lifecycle =
      LifecycleState.prepareState S.lifecycle S.plan.batch assignment := rfl

@[simp] theorem preparedController_version :
    (preparedController S assignment).plan.version = S.plan.version + 1 := rfl

@[simp] theorem preparedController_batch :
    (preparedController S assignment).plan.batch = empty := rfl
```

If `rfl` does not unfold the structure update, the only repair should be
`simp [preparedController, PlanHead.advance]`; do not redesign the state.

## Computed Restore transport

The root and child batch must be functions of the existing `Transfer.rho`.
They are not fields accepted from the runtime.

```lean
def transferFiber [Fintype Claim] [DecidableEq Claim]
    (tr : Transfer Claim Branch) (c : Claim) : Finset Claim :=
  Finset.univ.filter fun c' => tr.rho c' = some c

def childBatch [Fintype Claim] [DecidableEq Claim]
    (tr : Transfer Claim Branch) (U : Finset Claim) : Finset Claim :=
  Finset.univ.filter fun c' => exists c in U, tr.rho c' = some c

def childRootSlot (root : Claim -> Option Slot)
    (tr : Transfer Claim Branch) (c' : Claim) : Option Slot :=
  (tr.rho c').bind root

def PlanHead.afterTransfer [Fintype Claim] [DecidableEq Claim]
    (p : PlanHead Coord Claim Slot) (tr : Transfer Claim Branch) :
    PlanHead Coord Claim Slot :=
  { p with
    version := p.version + 1
    batch := childBatch tr p.batch
    rootSlot := childRootSlot p.rootSlot tr }
```

The first two structural lemmas should be proved by extensionality and `simp`:

```lean
@[simp] theorem childBatch_singleton (tr : Transfer Claim Branch) (c : Claim) :
    childBatch tr {c} = transferFiber tr c := by
  ext c'
  simp [childBatch, transferFiber]

@[simp] theorem childRootSlot_of_rho
    (root : Claim -> Option Slot) (tr : Transfer Claim Branch)
    (h : tr.rho c' = some c) :
    childRootSlot root tr c' = root c := by
  simp [childRootSlot, h]
```

The useful non-forgeability statement is then a theorem about the computed
transport, not a premise:

```lean
theorem afterTransfer_root_of_member
    (p : PlanHead Coord Claim Slot) (tr : Transfer Claim Branch)
    (hc' : c' in childBatch tr p.batch) :
    exists c in p.batch,
      tr.rho c' = some c /\
      (p.afterTransfer tr).rootSlot c' = p.rootSlot c := by
  have hmem : exists c in p.batch, tr.rho c' = some c := by
    simpa [childBatch] using hc'
  obtain ⟨c, hc, hrho⟩ := hmem
  exact ⟨c, hc, hrho, by simp [PlanHead.afterTransfer, hrho,
    childRootSlot]⟩
```

Use ASCII `->`, `exists`, `in`, and `/\` only if the source-writing agent
prefers them; ordinary Lean Unicode is equally fine.  The logical signature
above is the requirement.

## The one componentwise R/P bridge

Define only a short load abbreviation:

```lean
def batchLoad
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (k : Coord) : Nat :=
  sum c in U, A.auth.demand c k
```

For this singleton-root preflight, the full tentative root bundle and selected
batch are both refinements of the one source claim.  The following theorem is
the only new arithmetic bridge needed.  Both conclusions must flow from the
existing checked-transfer theorem; neither may be discharged only by
`native_decide` on the fixture.

```lean
theorem singleton_child_RP_bound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (source : Claim)
    (R P : Coord -> Nat)
    (valid : Transfer.CoreValid A tr)
    (source_le_R : forall k, A.auth.demand source k <= R k)
    (source_le_P : forall k, A.auth.demand source k <= P k) :
    forall k,
      batchLoad A (transferFiber tr source) k <= R k /\
      batchLoad A (childBatch tr {source}) k <= P k := by
  intro k
  have hfiber :
      batchLoad A (transferFiber tr source) k <=
        A.auth.demand source k := by
    simpa [batchLoad, transferFiber] using valid.fiber_demand source k
  constructor
  · exact hfiber.trans (source_le_R k)
  · rw [childBatch_singleton]
    exact hfiber.trans (source_le_P k)
```

This is deliberately not advertised as the full multi-claim slot theorem.
Its `R` interpretation is valid in the fixture because the source root slot
contains exactly `Claim.source`; the full run must later aggregate all source
claims in a slot.

The canonical target keeps the demand function definitionally unchanged.  If
the fixture theorem needs to state the load over the target lifecycle, add
only this bridge:

```lean
@[simp] theorem canonicalTarget_batchLoad
    (A) (tr) (op) (U) (k) :
    batchLoad (canonicalTarget A tr op) U k = batchLoad A U k := rfl
```

If `rfl` is too opaque, use
`simp [batchLoad, canonicalTarget, Transfer.targetCore]`.

## Authoritative head checker

The offered version is checked against the unique `ControllerState.plan`; it
is not accepted as an equality premise.

```lean
def checkHead (p : PlanHead Coord Claim Slot) (offered : Nat) : Bool :=
  decide (offered = p.version)

theorem checkHead_sound
    (p : PlanHead Coord Claim Slot) (offered : Nat)
    (h : checkHead p offered = true) : offered = p.version := by
  exact of_decide_eq_true h
```

If unfolding is required, the final line is
`simpa [checkHead] using (of_decide_eq_true h)`; more robustly:

```lean
  have : decide (offered = p.version) = true := by
    simpa [checkHead] using h
  exact of_decide_eq_true this
```

## Finite assignment checker

Keep the checker atomized so its soundness proof is three applications of the
existing `finiteAll_eq_true`.  `AssignmentValid` is checker output only; no
constructor accepts it from the runtime.

```lean
def checkAssignedMemberFresh
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation -> Option Claim) : Bool :=
  finiteAll Finset.univ fun e =>
    match assignment e with
    | none => true
    | some c => decide (c in U /\ A.opClaim e = none)

def checkAssignmentCovered
    (U : Finset Claim) (assignment : Operation -> Option Claim) : Bool :=
  finiteAll U fun c => decide (exists e, assignment e = some c)

def checkAssignmentInjective
    (assignment : Operation -> Option Claim) : Bool :=
  finiteAll Finset.univ fun e =>
    finiteAll Finset.univ fun e' =>
      decide (forall c,
        assignment e = some c -> assignment e' = some c -> e = e')

def checkAssignment
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation -> Option Claim) : Bool :=
  checkAssignedMemberFresh A U assignment &&
    (checkAssignmentCovered U assignment &&
      checkAssignmentInjective assignment)

structure AssignmentValid
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation -> Option Claim) : Prop where
  assigned_mem : forall e c, assignment e = some c -> c in U
  covered : forall c in U, exists e, assignment e = some c
  assignment_injective : forall e e' c,
    assignment e = some c -> assignment e' = some c -> e = e'
  fresh : forall e c, assignment e = some c -> A.opClaim e = none
```

Required soundness signature:

```lean
theorem checkAssignment_sound
    (hcheck : checkAssignment A U assignment = true) :
    AssignmentValid A U assignment
```

Proof tactic:

1. `simpa [checkAssignment, Bool.and_eq_true] using hcheck` to obtain the
   three atom equalities.
2. For `assigned_mem`/`fresh`, specialize
   `(finiteAll_eq_true Finset.univ _).mp hmember` at `e`, rewrite the offered
   assignment equality, and `simpa` to obtain the conjunction.
3. For `covered`, specialize
   `(finiteAll_eq_true U _).mp hcovered` at `c` and apply
   `of_decide_eq_true`.
4. For injectivity, specialize the two nested `finiteAll_eq_true` lemmas at
   `e` and `e'`, apply `of_decide_eq_true`, then apply the resulting function
   to `c` and the two assignment equalities.

No separate parser, schema, or desired-result Boolean is needed.

## Deriving actual `PrepareOK`

Do not define `HeadReady` as an opaque certificate.  The preflight theorem
should expose the four source obligations and derive `PrepareOK` from them.
They are then proved on the computed Restore target.

```lean
theorem prepare_head_is_ok
    (S : ControllerState Coord Claim Branch Grant Operation Slot)
    (offered : Nat) (assignment : Operation -> Option Claim)
    (hWF : S.lifecycle.LWF)
    (hHead : checkHead S.plan offered = true)
    (hAssignment :
      checkAssignment S.lifecycle S.plan.batch assignment = true)
    (hne : S.plan.batch.Nonempty)
    (htentative : forall c in S.plan.batch, exists b,
      S.lifecycle.auth.status c = .tentative b)
    (hbatchP : forall k,
      batchLoad S.lifecycle S.plan.batch k <=
        S.plan.P S.plan.currentSlot k)
    (hPfits : forall k,
      S.lifecycle.auth.durableLoad k +
        S.plan.P S.plan.currentSlot k <= S.lifecycle.auth.capacity k) :
    offered = S.plan.version /\
      LifecycleState.PrepareOK
        S.lifecycle S.plan.batch assignment := by
  have hver := checkHead_sound S.plan offered hHead
  have ha := checkAssignment_sound hAssignment
  refine ⟨hver, ?_⟩
  refine {
    nonempty := hne
    member_open := ?_
    base := ?_
    assigned_mem := ha.assigned_mem
    covered := ha.covered
    assignment_injective := ha.assignment_injective
    fresh := ha.fresh }
  · intro c hc
    obtain ⟨b, hs⟩ := htentative c hc
    exact ⟨b, hs, hWF.owner_open c b hs, hWF.grant_open c b hs⟩
  · intro k
    calc
      promotedLoad S.lifecycle.auth S.plan.batch k =
          S.lifecycle.auth.durableLoad k +
            batchLoad S.lifecycle S.plan.batch k := rfl
      _ <= S.lifecycle.auth.durableLoad k +
            S.plan.P S.plan.currentSlot k :=
        Nat.add_le_add_left (hbatchP k) _
      _ <= S.lifecycle.auth.capacity k := hPfits k
```

This construction uses `LWF` only to derive branch/grant openness from actual
tentativeness.  It does not take `PrepareOK`, target `LWF`, target `AC`, or any
target plan proposition as input.

## `PreparePlanned` and exact lifecycle projection

The smallest relation that demonstrates the intended linearization point is:

```lean
inductive PreparePlanned :
    ControllerState Coord Claim Branch Grant Operation Slot ->
    Nat -> (Operation -> Option Claim) ->
    ControllerState Coord Claim Branch Grant Operation Slot -> Prop where
  | mk {S offered assignment}
      (hWF : S.lifecycle.LWF)
      (hHead : checkHead S.plan offered = true)
      (hAssignment :
        checkAssignment S.lifecycle S.plan.batch assignment = true)
      (hne : S.plan.batch.Nonempty)
      (htentative : forall c in S.plan.batch, exists b,
        S.lifecycle.auth.status c = .tentative b)
      (hbatchP : forall k,
        batchLoad S.lifecycle S.plan.batch k <=
          S.plan.P S.plan.currentSlot k)
      (hPfits : forall k,
        S.lifecycle.auth.durableLoad k +
          S.plan.P S.plan.currentSlot k <= S.lifecycle.auth.capacity k) :
      PreparePlanned S offered assignment
        (preparedController S assignment)
```

Its projection must be the repository's actual `Step.core/CoreStep.prepare`,
not a parallel abstract relation:

```lean
theorem PreparePlanned.actual_step
    (h : PreparePlanned S offered assignment S') :
    Step S.lifecycle (.tau) S'.lifecycle := by
  cases h with
  | mk hWF hHead hAssignment hne htentative hbatchP hPfits =>
      have hOK := (prepare_head_is_ok S offered assignment hWF hHead
        hAssignment hne htentative hbatchP hPfits).2
      simpa [preparedController] using
        (Step.core (CoreStep.prepare hOK))

theorem PreparePlanned.head_advanced
    (h : PreparePlanned S offered assignment S') :
    S'.plan.version = S.plan.version + 1 /\ S'.plan.batch = empty := by
  cases h
  simp [preparedController, PlanHead.advance]
```

Thus the head/version change and exact `prepareState` occur in the same
controller transition.  There is no window in this abstract specification in
which one happens without the other.

## Revoke and actual Dispatch after Prepare

Use computed pair targets and make no general claim that Revoke preserves a
nonempty residual plan.  In this one-batch preflight, first prove
`afterPrepare.plan.batch = empty`; only then stutter the plan through Revoke.

```lean
def revokeController
    (S : ControllerState Coord Claim Branch Grant Operation Slot) (g : Grant) :
    ControllerState Coord Claim Branch Grant Operation Slot where
  lifecycle := LifecycleState.revokeState S.lifecycle g
  plan := S.plan

def dispatchController
    (S : ControllerState Coord Claim Branch Grant Operation Slot)
    (e : Operation) (c : Claim) :
    ControllerState Coord Claim Branch Grant Operation Slot where
  lifecycle := LifecycleState.setTicketPhase S.lifecycle e c .inflight
  plan := S.plan

theorem revoke_done_actual_step (hdone : S.plan.batch = empty) :
    Step S.lifecycle (.tau) (revokeController S g).lifecycle := by
  exact Step.core (CoreStep.revoke S.lifecycle g)

theorem dispatch_actual_step
    (hticket : S.lifecycle.tickets e = some ⟨c, .prepared⟩) :
    Step S.lifecycle (.attempt e c) (dispatchController S e c).lifecycle := by
  exact Step.core (CoreStep.ticket (TicketStep.dispatch hticket))
```

The unused `hdone` in `revoke_done_actual_step` is intentional: the actual
lifecycle Revoke is always defined, while the premise justifies stuttering
the *plan*.  Do not delete it and accidentally claim nonempty-plan transport.

The durable-ticket bridge should be one generic lemma:

```lean
theorem revoke_then_dispatch
    (hdone : S.plan.batch = empty)
    (hticket : S.lifecycle.tickets e = some ⟨c, .prepared⟩) :
    let R := revokeController S g
    let D := dispatchController R e c
    Step S.lifecycle (.tau) R.lifecycle /\
    Step R.lifecycle (.attempt e c) D.lifecycle /\
    R.plan = S.plan /\ D.plan = S.plan := by
  have hticket' :
      (revokeController S g).lifecycle.tickets e =
        some ⟨c, .prepared⟩ := by
    simpa [revokeController, LifecycleState.revokeState,
      LifecycleState.restrictLifecycle] using hticket
  exact ⟨revoke_done_actual_step hdone,
    dispatch_actual_step hticket', rfl, rfl⟩
```

Most importantly, `dispatch_actual_step` quantifies over an arbitrary current
`S.plan` and has no `offered`, `checkHead`, certificate, or version premise.
This is the formal statement that after atomic Prepare, Dispatch uses the
durable ticket rather than rechecking the consumed plan.  With source `LWF`
and `AC`, reuse `revoke_preserves_wf_ac` and `step_attempt_safe` to obtain the
existing durable-before-attempt conclusion; do not restate or reprove it.

## Exact finite fixture

Use these definitions in a small `PlanPreflight` namespace:

```lean
open AuthorityContinuity.TopologyExamples

abbrev Slot := Fin 1

def sourcePlan : PlanHead Coord Claim Slot where
  version := 0
  currentSlot := 0
  batch := {Claim.source}
  rootSlot := fun c => if c = Claim.source then some 0 else none
  R := fun _ _ => 2
  P := fun _ _ => 2

def sourceController :
    ControllerState Coord Claim Branch Grant Operation Slot where
  lifecycle := TopologyExamples.source
  plan := sourcePlan

def restoreOp : CanonicalOp Branch :=
  .replaceRestore Branch.parent Branch.right

def afterRestore :
    ControllerState Coord Claim Branch Grant Operation Slot where
  lifecycle := canonicalTarget TopologyExamples.source replaceTransfer restoreOp
  plan := sourcePlan.afterTransfer replaceTransfer

def childAssignment : Operation -> Option Claim :=
  fun _ => some Claim.leftFragment
```

Required fixture lemmas, in this order:

1. `restore_actual_step`: use `Step.canonical replaceTransfer restoreOp
   replace_restore_admission_accepts` and prove `checkHead sourcePlan 0 = true`
   separately by `native_decide`.
2. `child_batch_exact`: `afterRestore.plan.batch = {Claim.leftFragment}` by
   `native_decide` (the value is computed by `rho`, not proposed).
3. `child_root_exact`: the child root is `some 0`, preferably by
   `afterTransfer_root_of_member`; `native_decide` may additionally sanity
   check the concrete value.
4. `child_RP_bound`: derive `Transfer.CoreValid` with
   `(checkCanonical_sound ... replace_restore_admission_accepts).transfer.toCoreValid`
   and instantiate `singleton_child_RP_bound` with constant `R=P=2`.
   A concrete `native_decide` is only a control, not the proof.
5. `afterRestore_lwf_ac`: reuse `replaceRestore_preserves_wf_ac` with
   `source_lwf`, `source_ac`, `source_active_exact`, and the existing admission
   theorem.
6. `assignment_accepts`: `checkAssignment afterRestore.lifecycle
   afterRestore.plan.batch childAssignment = true` by `native_decide`.
7. Prove the raw `hne`, `htentative`, `hbatchP`, and `hPfits` obligations by
   `simp`/`native_decide`, using `child_batch_exact` and `child_RP_bound` rather
   than inventing `PrepareOK`.
8. Construct `PreparePlanned afterRestore 1 childAssignment afterPrepare`.
   Here `1` is the post-Restore authoritative version; `checkHead` must accept
   it.  Optionally record that `checkHead afterRestore.plan 0 = false`, but do
   not make that extra Boolean a success gate.
9. From `PreparePlanned.actual_step`, obtain the exact lifecycle Prepare step;
   from `PreparePlanned.head_advanced`, obtain version `2` and empty batch.
10. Unfold `LifecycleState.prepareState` once to prove the actual operation-0
    ticket is `some ⟨Claim.leftFragment, .prepared⟩`; run
    `revoke_then_dispatch` with grant `0`.
11. Apply the existing `step_attempt_safe` to the dispatch step after deriving
    post-Revoke `LWF`.  This is the actual durable-before-attempt endpoint.

The final preflight theorem may simply conjoin the already named lemmas.  Do
not write one deeply nested proof before the components compile.

## Compile-risk order within each of the at most three attempts

The single source snapshot for an attempt should contain all items above, but
proof construction should follow this order before invoking Lean:

1. data/computed transport plus `childBatch_singleton`;
2. `singleton_child_RP_bound` using the existing `fiber_demand` field;
3. `checkHead_sound` and `checkAssignment_sound`;
4. `prepare_head_is_ok`, `PreparePlanned.actual_step`, and head-advance simp;
5. the replacing-Restore fixture, Revoke, and Dispatch endpoint.

Likely local repair points are only namespace qualification, Boolean
conjunction reassociation, or one definitional `simp`.  A failure requiring a
caller-supplied target invariant, an assumed `PrepareOK`, or replacement of
the actual lifecycle relation is not a proof-engineering repair and must stop
the attempt.

## Circularity audit

| Possible shortcut | Status in this architecture |
|---|---|
| Caller supplies child batch | Forbidden; `childBatch tr p.batch` is a definition of `rho`. |
| Caller supplies target root/slot | Forbidden; `childRootSlot` is `Option.bind tr.rho p.rootSlot`. |
| R/P bound checked against desired output | Forbidden; both bounds derive from existing `Transfer.CoreValid.fiber_demand`. |
| Offered version asserted equal | Forbidden; only `checkHead = true` is admitted and `checkHead_sound` derives equality. |
| Assignment facts asserted | Forbidden; finite checker derives membership, coverage, injectivity, and freshness. |
| `PrepareOK` stored in plan or constructor | Forbidden; `prepare_head_is_ok` constructs every field from current state, source invariants, and checker outputs. |
| Target `LWF`, `AC`, or plan validity supplied | Absent.  The target lifecycle is definitionally the existing `prepareState`. |
| Head advance separate from Prepare | Absent; `preparedController` pairs exact `prepareState` with `PlanHead.advance` in one target. |
| Revoke claimed to preserve arbitrary residual plans | Forbidden; the stutter lemma requires the current batch to be empty. |
| Dispatch rechecks old version/certificate | Absent by theorem signature; `dispatch_actual_step` depends only on the durable prepared ticket. |
| New abstract attempt semantics | Absent; endpoint is the existing `TicketStep.dispatch`, embedded in actual `Step`. |
| Physical exactly-once conclusion | Absent; the endpoint proves only the existing stable logical binding and durable-before-attempt result. |

Passing this preflight establishes path executability only.  It does not prove
multi-slot tail preservation, arbitrary-depth transport, general same-slot
Merge, or the full trace theorem.
