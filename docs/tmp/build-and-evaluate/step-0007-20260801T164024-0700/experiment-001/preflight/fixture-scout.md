# Static fixture scout for the Step 0007 Lean preflight

## Scope and evidence status

This report is a static audit of every current file under
`lean/AuthorityContinuity/`.  In particular, it follows the actual definitions
in `TopologyExamples.lean`, `Lifecycle.lean`, `Topology.lean`, `Transfer.lean`,
`Step.lean`, and `Audit.lean`.  Per the scouting instruction, I did **not** invoke
Lean or Lake and did not edit Lean source.  Consequently:

- all names and theorem types quoted below already occur in the checked source;
- definitional reductions are listed field by field, so the preflight author
  need not guess the semantic path; and
- the final glue snippet is a candidate for retained preflight attempt 1, not a
  claim that this new snippet has already elaborated.

## Smallest existing invariant-complete source

The smallest existing source that already has all three required proofs is
`AuthorityContinuity.TopologyExamples.source`:

```lean
abbrev Coord := Fin 1
abbrev Claim := Fin 3
abbrev Branch := Fin 3
abbrev Grant := Fin 1
abbrev Operation := Fin 1

def source : LifecycleState Coord Claim Branch Grant Operation

theorem source_lwf : source.LWF
theorem source_ac : AC source.auth
theorem source_active_exact : source.ActiveExact
```

The concrete IDs are:

```lean
Claim.source        = 0
Claim.leftFragment  = 1
Claim.rightFragment = 2
Branch.parent       = 0
Branch.left         = 1
Branch.right        = 2
```

Its only tentative claim is `Claim.source`, owned by `Branch.parent`, with
demand 2 in the sole coordinate and capacity 2.  Both fragment IDs are
unissued, each has demand 1, all claims use the sole open grant, the parent is
the sole open branch, and all ticket/receipt entries are `none`.  These facts
come directly from `TopologyExamples.source` (lines 38--50), not from a new
fixture assumption.

## Recommended canonical operation: replacing Restore

For the thinnest vertical lifecycle path, reuse:

```lean
def replaceTransfer : Transfer Claim Branch

theorem replace_restore_admission_accepts :
  checkCanonical source replaceTransfer
    (.replaceRestore .parent .right) = true
```

`replaceTransfer` has exactly one target fiber member:

```text
rho(Claim.leftFragment)   = some Claim.source
owner(Claim.leftFragment) = some Branch.right
rho/owner of every other claim = none
```

This is smaller than `splitTransfer`: the computed child batch is a singleton,
the sole operation ID can cover it, and after Prepare the planned batch is
empty.  Therefore a subsequent Revoke changes real lifecycle state while
leaving no unconsumed plan tail to update; it is the cleanest post-Prepare
ticket-survival witness.

Use the following abbreviations in the preflight module:

```lean
open LifecycleState

def restoreOp : CanonicalOp Branch :=
  .replaceRestore Branch.parent Branch.right

def restored : LifecycleState Coord Claim Branch Grant Operation :=
  canonicalTarget source replaceTransfer restoreOp
```

The actual admitted topology edge is constructed by the real paper-facing
relation, not by equality of hand-written states:

```lean
theorem restore_step : Step source .tau restored :=
  Step.canonical replaceTransfer restoreOp
    replace_restore_admission_accepts
```

The target invariant triple follows from the existing theorem with no target
invariant premise:

```lean
theorem restored_invariants :
    restored.LWF ∧ AC restored.auth ∧ restored.ActiveExact :=
  replaceRestore_preserves_wf_ac source replaceTransfer
    Branch.parent Branch.right source_lwf source_ac source_active_exact
    replace_restore_admission_accepts
```

The relevant existing theorem type is:

```lean
replaceRestore_preserves_wf_ac
  (A) (tr) (parent restored)
  (hWF : A.LWF) (hAC : AC A.auth) (hActive : A.ActiveExact)
  (hcheck : checkCanonical A tr (.replaceRestore parent restored) = true) :
  (canonicalTarget A tr (.replaceRestore parent restored)).LWF ∧
  AC (canonicalTarget A tr (.replaceRestore parent restored)).auth ∧
  (canonicalTarget A tr (.replaceRestore parent restored)).ActiveExact
```

### Alternative when the preflight must visibly branch

The existing nontrivial split path is also ready-made:

```lean
def splitTransfer : Transfer Claim Branch

theorem parallel_fork_admission_accepts :
  checkCanonical source splitTransfer
    (.parallelFork .parent .left .right) = true

theorem fresh_fragment_parallel_preflight :
  (canonicalTarget source splitTransfer
      (.parallelFork .parent .left .right)).LWF ∧
  AC (canonicalTarget source splitTransfer
      (.parallelFork .parent .left .right)).auth ∧
  (canonicalTarget source splitTransfer
      (.parallelFork .parent .left .right)).ActiveExact
```

`splitTransfer` maps both fragment IDs to `Claim.source`, with owners left and
right.  It is the better later full-run witness for a source slot expanding to
multiple leaves.  It is not the smallest Prepare/Dispatch preflight because
`Operation = Fin 1` cannot injectively cover both fragments in one Prepare.

## Direct root-slot and computed-batch bound

For the singleton source batch `{Claim.source}`, the plan's computed child-batch
rule

```text
U' = { c' | exists c in U, replaceTransfer.rho c' = some c }
```

reduces exactly to the existing source fiber

```lean
Finset.univ.filter fun c' =>
  replaceTransfer.rho c' = some Claim.source
```

and, by the definition of `replaceTransfer`, this set has the sole member
`Claim.leftFragment`.  Do not introduce a caller-chosen target batch: define it
from `rho`, then prove its equality to the singleton in the finite fixture.

The desired load bound is already one field projection from checker soundness;
no general reindexing theorem is needed in the preflight:

```lean
theorem restored_root_fiber_bound (k : Coord) :
    (∑ c' ∈ Finset.univ.filter (fun c' =>
        replaceTransfer.rho c' = some Claim.source),
      source.auth.demand c' k) ≤
      source.auth.demand Claim.source k :=
  ((checkCanonical_sound source replaceTransfer restoreOp
      replace_restore_admission_accepts).transfer.toCoreValid.fiber_demand
    Claim.source k)
```

The exact existing field type is:

```lean
Transfer.CoreValid.fiber_demand : ∀ c k,
  (∑ c' ∈ Finset.univ.filter (fun c' => tr.rho c' = some c),
    A.auth.demand c' k) ≤ A.auth.demand c k
```

For this fixture the inequality computes to `1 <= 2`.  It serves both of the
thin preflight obligations:

- target `R`: all live tentative demand descended from the root slot is 1,
  bounded by the source envelope 2;
- child `P`: because the source batch is exactly `{Claim.source}`, the computed
  child batch is exactly this fiber, so its demand 1 is bounded by source batch
  demand 2.

The full run still needs the general distinction between all slot demand `R`
and selected batch demand `P`; this coincidence is specific to the admitted
minimal fixture and must not be generalized.

## Constructing the real nonempty `PrepareOK`

Use the computed child batch after proving it equals the singleton; for the
field-by-field glue, the following abbreviations expose the same set directly:

```lean
def prepareBatch : Finset Claim := {Claim.leftFragment}

def prepareAssignment : Operation → Option Claim :=
  fun _ => some Claim.leftFragment
```

The assignment is nonempty and injective because `Operation = Fin 1`.  The
actual structure that must be constructed is exactly
`LifecycleState.PrepareOK` from `Lifecycle.lean` lines 394--406:

```lean
structure PrepareOK (A) (U) (assignment) : Prop where
  nonempty : U.Nonempty
  member_open : ∀ c ∈ U, ∃ b,
    A.auth.status c = .tentative b ∧
    A.branchEpoch b = .open ∧ A.claimOpen c
  base : ∀ k, promotedLoad A.auth U k ≤ A.auth.capacity k
  assigned_mem : ∀ e c, assignment e = some c → c ∈ U
  covered : ∀ c ∈ U, ∃ e, assignment e = some c
  assignment_injective : ∀ e e' c,
    assignment e = some c → assignment e' = some c → e = e'
  fresh : ∀ e c, assignment e = some c → A.opClaim e = none
```

Every field has concrete source evidence:

| `PrepareOK` field | Concrete evidence in `restored` |
|---|---|
| `nonempty` | `Claim.leftFragment ∈ {Claim.leftFragment}` |
| `member_open` | transfer target status is `.tentative Branch.right`; replacing Restore opens `Branch.right`; `grantOf` and `grantEpoch` are preserved and the sole grant is open |
| `base` | durable load is 0, selected demand is 1, capacity is 2 |
| `assigned_mem` | the constant assignment can return only `Claim.leftFragment` |
| `covered` | operation `(0 : Operation)` maps to `Claim.leftFragment` |
| `assignment_injective` | `Fin 1` is a subsingleton |
| `fresh` | `canonicalTarget_opClaim` preserves `source.opClaim`, and source has neither a ticket nor a receipt |

A conservative field-by-field proof skeleton for retained attempt 1 is:

```lean
theorem restored_prepare_ok :
    PrepareOK restored prepareBatch prepareAssignment := by
  refine {
    nonempty := by simp [prepareBatch]
    member_open := ?_
    base := ?_
    assigned_mem := ?_
    covered := ?_
    assignment_injective := ?_
    fresh := ?_
  }
  · intro c hc
    have hc' : c = Claim.leftFragment := by
      simpa [prepareBatch] using hc
    subst c
    exact ⟨Branch.right, rfl, rfl, rfl⟩
  · intro k
    fin_cases k
    native_decide
  · intro e c h
    have hc : c = Claim.leftFragment := by
      simpa [prepareAssignment] using h.symm
    simpa [prepareBatch, hc]
  · intro c hc
    have hc' : c = Claim.leftFragment := by
      simpa [prepareBatch] using hc
    subst c
    exact ⟨(0 : Operation), rfl⟩
  · intro e e' c he he'
    exact Subsingleton.elim e e'
  · intro e c h
    simpa [restored, source, LifecycleState.opClaim] using
      (canonicalTarget_opClaim source replaceTransfer restoreOp e)
```

Two proof-engineering notes for attempt 1:

1. The `member_open` equalities and prepared-ticket equality below reduce by
   the concrete `if`/match tables.  If elaboration does not close them by `rfl`,
   unfold only `restored`, `restoreOp`, `canonicalTarget`,
   `Transfer.targetCore`, `Transfer.targetStatus`, `replaceTransfer`, and the
   relevant lifecycle accessor; do not replace them with assumptions.
2. The displayed `assigned_mem` proof may be simplified by `simp` differently
   by the pinned Mathlib version.  Its semantic proof is only `Option.some`
   injectivity followed by singleton membership.  This is local glue, not a
   theorem risk.

## Exact Prepare, post-Prepare Revoke, and Dispatch path

The targets should be definitions of the real lifecycle functions:

```lean
def prepared : LifecycleState Coord Claim Branch Grant Operation :=
  prepareState restored prepareBatch prepareAssignment

def revoked : LifecycleState Coord Claim Branch Grant Operation :=
  revokeState prepared (0 : Grant)

def dispatched : LifecycleState Coord Claim Branch Grant Operation :=
  setTicketPhase revoked (0 : Operation) Claim.leftFragment .inflight
```

The actual relation edges are then:

```lean
theorem prepare_step : Step restored .tau prepared :=
  Step.core (CoreStep.prepare restored_prepare_ok)

theorem revoke_step : Step prepared .tau revoked :=
  Step.core (CoreStep.revoke prepared (0 : Grant))

theorem prepared_ticket :
    prepared.tickets (0 : Operation) =
      some ⟨Claim.leftFragment, TicketPhase.prepared⟩ := by
  rfl

theorem revoked_ticket :
    revoked.tickets (0 : Operation) =
      some ⟨Claim.leftFragment, TicketPhase.prepared⟩ := by
  simpa [revoked, revokeState, restrictLifecycle] using prepared_ticket

theorem dispatch_ticket_step :
    TicketStep revoked
      (.attempt (0 : Operation) Claim.leftFragment) dispatched :=
  TicketStep.dispatch revoked_ticket

theorem dispatch_step :
    Step revoked (.attempt (0 : Operation) Claim.leftFragment) dispatched :=
  Step.core (CoreStep.ticket dispatch_ticket_step)
```

This is the exact semantic boundary needed by the paper story:

1. `prepareState` atomically changes the claim to `.durable` and installs the
   `(operation, claim, prepared)` ticket.
2. `revokeState` terminalizes only remaining tentative claims for the grant and
   changes the grant epoch; its definition retains tickets and receipts.
3. `TicketStep.dispatch` checks only the prepared ticket and changes its phase
   to `inflight`.  Its constructor has no grant, branch, topology, certificate,
   or plan-version premise.

The invariant chain can use only existing preservation theorems:

```lean
theorem prepared_invariants :
    prepared.LWF ∧ AC prepared.auth ∧ prepared.ActiveExact := by
  have hWA := LifecycleState.prepare_preserves_wf_ac
    restored prepareBatch prepareAssignment
    restored_invariants.1 restored_invariants.2.1 restored_prepare_ok
  exact ⟨hWA.1, hWA.2,
    LifecycleState.prepare_preserves_active_exact
      restored prepareBatch prepareAssignment
      restored_invariants.1 restored_invariants.2.2 restored_prepare_ok⟩

theorem revoked_invariants :
    revoked.LWF ∧ AC revoked.auth ∧ revoked.ActiveExact :=
  step_preserves_wf_ac revoke_step
    prepared_invariants.1 prepared_invariants.2.1 prepared_invariants.2.2

theorem dispatched_invariants :
    dispatched.LWF ∧ AC dispatched.auth ∧ dispatched.ActiveExact :=
  step_preserves_wf_ac dispatch_step
    revoked_invariants.1 revoked_invariants.2.1 revoked_invariants.2.2

theorem dispatched_uses_durable_ticket :
    revoked.opClaim (0 : Operation) = some Claim.leftFragment ∧
    revoked.auth.status Claim.leftFragment = .durable ∧
    dispatched.opClaim (0 : Operation) = some Claim.leftFragment :=
  step_attempt_safe dispatch_step revoked_invariants.1
```

Existing theorem roles in this chain are exact:

- `prepare_preserves_wf_ac` derives target `LWF` and `AC` from source
  invariants and real `PrepareOK`;
- `LifecycleState.prepare_preserves_active_exact` derives the third invariant;
- `step_preserves_wf_ac` covers the actual Revoke and Dispatch `Step`s; and
- `step_attempt_safe` proves durable-before-attempt and stable binding.

## Important boundary: what is not in the current Lean model

A complete search of `lean/AuthorityContinuity/` finds no plan, root-slot,
head/version, CAS, or `PreparePlanned` definition.  Thus the existing model can
provide the lifecycle projection above, but it cannot by itself prove that
Revoke “stutters on the plan” or that an authoritative head was atomically
consumed.  Those must be new fields/constructors in the Step 0007 extended
controller state, with projection lemmas to the exact `Step`s shown here.

In particular:

- do not present `replace_restore_admission_accepts` as a plan-head check; it is
  only the actual canonical lifecycle admission check;
- do not add `PrepareOK` or target plan validity as certificate premises;
- the new `PreparePlanned` constructor should derive `restored_prepare_ok`-like
  fields from source plan validity plus an assignment checker, then project
  definitionally to `prepareState`; and
- after that projection, Dispatch must reuse `revoked_ticket` alone.  Rechecking
  the consumed plan/version at Dispatch would contradict the actual
  `TicketStep.dispatch` boundary.

## Minimal recommendation

Use replacing Restore for retained preflight attempt 1.  It reuses the smallest
proved source, gives a real checked history transformation, makes the computed
child batch a one-element `rho` fiber, admits a real nonempty Prepare with the
sole operation ID, consumes the whole batch, and supports the strongest small
post-Prepare witness: actual Revoke followed by actual ticket Dispatch.

Keep `splitTransfer` plus `fresh_fragment_parallel_preflight` for the full-run
multi-leaf slot theorem.  Switching the thin preflight to parallel Fork would
force either a partial batch or a larger Operation fixture and would add proof
surface without testing a different lifecycle boundary.
