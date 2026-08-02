import AuthorityContinuity.PlanInvariant

/-!
# Coherent rich schedules and exact discrete leaf accounting

`PlanInvariant.PlanData` proves multi-slot lifecycle safety, while
`Plan.AuthorityPlan` records a finite leaf disposition and the exact equation
`B + E + W = P`.  This module pairs the two without accepting a caller-proposed
target ledger.  Its Prepare target is computed from the source controller and
the repository's actual `prepareState`, including deterministic cleanup.
-/

namespace AuthorityContinuity.FullPlanInvariant

open AuthorityContinuity LifecycleState
open AuthorityContinuity.Plan
open AuthorityContinuity.PlanInvariant
open AuthorityContinuity.PlanInvariant.PlanData

universe uC uI uB uG uO uS

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO} {Slot : Type uS}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [LinearOrder Claim]
variable [Fintype Branch] [LinearOrder Branch]
variable [DecidableEq Grant] [Fintype Operation] [DecidableEq Operation]
variable [Fintype Slot] [LinearOrder Slot]

/-- The safety schedule and the exact finite leaf ledger are both durable
controller state. -/
structure FullPlan where
  schedule : PlanInvariant.PlanData
    (Coord := Coord) (Claim := Claim) (Slot := Slot)
  ledger : Plan.AuthorityPlan
    (Coord := Coord) (Claim := Claim) (Slot := Slot)

/-- Cross-layer representation agreement.  Global root equality is stronger
than equality only on extant leaves and makes historical lineage explicit. -/
structure Coherent
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)) : Prop where
  version_eq : p.ledger.version = p.schedule.version
  remaining_eq : p.ledger.remaining = p.schedule.remaining
  leafRoot_eq : p.ledger.leafRoot = p.schedule.rootSlot
  R_eq : p.ledger.R = p.schedule.R
  P_eq : p.ledger.P = p.schedule.P
  E_eq : p.ledger.E = p.schedule.E
  current_eq : ∀ s b, p.schedule.firstGroup A = some (s, b) ->
    p.ledger.currentSlot = s

/-- The combined invariant contains both the rich safety certificate and exact
discrete accounting. -/
structure FullInvariant
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)) : Prop where
  schedule_valid : p.schedule.Valid A
  coherent : Coherent A p
  exact : p.ledger.ExactAccounting A

structure FullState where
  lifecycle : LifecycleState Coord Claim Branch Grant Operation
  plan : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)

namespace FullPlan

/-- Demand promoted in a schedule row by the computed owner-group Prepare. -/
def promotedAt
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (q : PlanInvariant.PlanData
      (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (s : Slot) (k : Coord) : Nat :=
  match q.firstGroup A with
  | none => 0
  | some (headSlot, _) =>
      if s = headSlot then Plan.batchLoad A (q.headGroup A) k else 0

/-- If work remains, use the target's recomputed cursor slot.  On an empty tail
the old value is an inert fallback because `current_eq` has no premise. -/
def nextCurrent
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (q : PlanInvariant.PlanData
      (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (fallback : Slot) : Slot :=
  match q.firstGroup A with
  | some (s, _) => s
  | none => fallback

/-- Exact leaf classification after owner-group Prepare and actual cleanup. -/
def prepareDisposition
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) (c : Claim) :
    Option Plan.LeafDisposition :=
  let U := p.schedule.headGroup A
  let targetRemaining :=
    (p.schedule.afterPrepareGroup A assignment).remaining
  if c ∈ U then some .prepared
  else if c ∈ targetRemaining then some .remaining
  else if c ∈ p.schedule.remaining then some .withdrawn
  else if p.ledger.disposition c = some .remaining then some .withdrawn
  else p.ledger.disposition c

/-- The exact ledger target.  In particular, `W` is derived from the source
batch, exact promoted row, and actual post-cleanup target batch. -/
def afterPrepareLedger
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) :
    Plan.AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot) :=
  let U := p.schedule.headGroup A
  let A' := prepareState A U assignment
  let q' := p.schedule.afterPrepareGroup A assignment
  { version := q'.version
    currentSlot := nextCurrent A' q' p.ledger.currentSlot
    disposition := prepareDisposition A p assignment
    leafRoot := q'.rootSlot
    R := q'.R
    P := q'.P
    E := q'.E
    W := fun s k => p.ledger.W s k +
      (p.ledger.B A s k - (promotedAt A p.schedule s k + q'.B A' s k)) }

/-- Both target components are computed; neither is accepted from a caller. -/
def afterPrepare
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) :
    FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot) where
  schedule := p.schedule.afterPrepareGroup A assignment
  ledger := p.afterPrepareLedger A assignment

@[simp] theorem afterPrepareLedger_W
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) (s : Slot) (k : Coord) :
    (p.afterPrepareLedger A assignment).W s k = p.ledger.W s k +
      (p.ledger.B A s k -
        (promotedAt A p.schedule s k +
          (p.schedule.afterPrepareGroup A assignment).B
            (prepareState A (p.schedule.headGroup A) assignment) s k)) := rfl

theorem target_remaining_not_promoted
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim) {c : Claim}
    (hc : c ∈ (p.schedule.afterPrepareGroup A assignment).remaining) :
    c ∉ p.schedule.headGroup A := by
  intro hhead
  have hcFilter : c ∈ p.schedule.remaining.filter fun c =>
      ∃ b, (prepareState A (p.schedule.headGroup A) assignment).auth.status c =
        .tentative b := by
    simpa [PlanInvariant.PlanData.afterPrepareGroup] using hc
  obtain ⟨b, htentative⟩ := (Finset.mem_filter.mp hcFilter).2
  have hdurable := PlanInvariant.PlanData.prepareState_headGroup_status_durable
    (p := p.schedule) assignment hhead
  rw [hdurable] at htentative
  cases htentative

@[simp] theorem afterPrepareLedger_promoted
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) {c : Claim}
    (hc : c ∈ p.schedule.headGroup A) :
    (p.afterPrepareLedger A assignment).disposition c = some .prepared := by
  simp [afterPrepareLedger, prepareDisposition, hc]

@[simp] theorem afterPrepareLedger_surviving
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) {c : Claim}
    (hc : c ∈ (p.schedule.afterPrepareGroup A assignment).remaining) :
    (p.afterPrepareLedger A assignment).disposition c = some .remaining := by
  have hnot := target_remaining_not_promoted (p := p) assignment hc
  simp [afterPrepareLedger, prepareDisposition, hnot, hc]

@[simp] theorem afterPrepareLedger_cleaned
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) {c : Claim}
    (hsource : c ∈ p.schedule.remaining)
    (hhead : c ∉ p.schedule.headGroup A)
    (htarget : c ∉ (p.schedule.afterPrepareGroup A assignment).remaining) :
    (p.afterPrepareLedger A assignment).disposition c = some .withdrawn := by
  simp [afterPrepareLedger, prepareDisposition, hsource, hhead, htarget]

/-- Every source remaining leaf follows exactly one semantic Prepare outcome. -/
theorem source_remaining_classified
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) {c : Claim}
    (hc : c ∈ p.schedule.remaining) :
    (c ∈ p.schedule.headGroup A ∧
        (p.afterPrepareLedger A assignment).disposition c = some .prepared) ∨
      (c ∉ p.schedule.headGroup A ∧
        c ∈ (p.schedule.afterPrepareGroup A assignment).remaining ∧
        (p.afterPrepareLedger A assignment).disposition c = some .remaining) ∨
      (c ∉ p.schedule.headGroup A ∧
        c ∉ (p.schedule.afterPrepareGroup A assignment).remaining ∧
        (p.afterPrepareLedger A assignment).disposition c = some .withdrawn) := by
  by_cases hhead : c ∈ p.schedule.headGroup A
  · exact Or.inl ⟨hhead,
      afterPrepareLedger_promoted A p assignment hhead⟩
  by_cases htarget :
      c ∈ (p.schedule.afterPrepareGroup A assignment).remaining
  · exact Or.inr (Or.inl ⟨hhead, htarget,
      afterPrepareLedger_surviving A p assignment htarget⟩)
  · exact Or.inr (Or.inr ⟨hhead, htarget,
      afterPrepareLedger_cleaned A p assignment hc hhead htarget⟩)

/-- The finite disposition ledger exposes exactly the actual target remaining
set, independent of demand values. -/
@[simp] theorem afterPrepareLedger_remaining
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) :
    (p.afterPrepareLedger A assignment).remaining =
      (p.schedule.afterPrepareGroup A assignment).remaining := by
  ext c
  simp only [Plan.AuthorityPlan.remaining, Plan.AuthorityPlan.leaves,
    Finset.mem_filter, Finset.mem_univ, true_and]
  constructor
  · intro hdisposition
    by_cases hhead : c ∈ p.schedule.headGroup A
    · simp [afterPrepareLedger, prepareDisposition, hhead] at hdisposition
    by_cases htarget :
        c ∈ (p.schedule.afterPrepareGroup A assignment).remaining
    · exact htarget
    by_cases hsource : c ∈ p.schedule.remaining
    · simp [afterPrepareLedger, prepareDisposition, hhead, htarget, hsource]
        at hdisposition
    by_cases hghost : p.ledger.disposition c = some .remaining
    · simp [afterPrepareLedger, prepareDisposition, hhead, htarget, hsource,
        hghost] at hdisposition
    · simp [afterPrepareLedger, prepareDisposition, hhead, htarget, hsource,
        hghost] at hdisposition
  · intro htarget
    exact afterPrepareLedger_surviving A p assignment htarget

/-- Zero-vector leaves cannot disappear through arithmetic: every source
remaining leaf receives an explicit target disposition. -/
theorem zeroDemand_source_leaf_visible
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) {c : Claim}
    (hc : c ∈ p.schedule.remaining)
    (_zero : ∀ k, A.auth.demand c k = 0) :
    ∃ d, (p.afterPrepareLedger A assignment).disposition c = some d := by
  by_cases hhead : c ∈ p.schedule.headGroup A
  · exact ⟨.prepared, afterPrepareLedger_promoted A p assignment hhead⟩
  by_cases htarget :
      c ∈ (p.schedule.afterPrepareGroup A assignment).remaining
  · exact ⟨.remaining, afterPrepareLedger_surviving A p assignment htarget⟩
  · exact ⟨.withdrawn,
      afterPrepareLedger_cleaned A p assignment hc hhead htarget⟩

theorem afterPrepare_coherent
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) :
    Coherent (prepareState A (p.schedule.headGroup A) assignment)
      (p.afterPrepare A assignment) := by
  refine {
    version_eq := rfl
    remaining_eq := afterPrepareLedger_remaining A p assignment
    leafRoot_eq := rfl
    R_eq := rfl
    P_eq := rfl
    E_eq := rfl
    current_eq := ?_ }
  intro s b hfirst
  change (p.schedule.afterPrepareGroup A assignment).firstGroup
      (prepareState A (p.schedule.headGroup A) assignment) = some (s, b)
    at hfirst
  change nextCurrent
      (prepareState A (p.schedule.headGroup A) assignment)
      (p.schedule.afterPrepareGroup A assignment) p.ledger.currentSlot = s
  simp [nextCurrent, hfirst]

theorem Coherent.ledger_B_eq_schedule_B
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (h : Coherent A p) (s : Slot) (k : Coord) :
    p.ledger.B A s k = p.schedule.B A s k := by
  unfold Plan.AuthorityPlan.B PlanInvariant.PlanData.B
    PlanInvariant.PlanData.rootRemaining Plan.rootBatchLoad Plan.rootBatch
  rw [h.remaining_eq, h.leafRoot_eq]

theorem afterPrepare_E_eq_add_promotedAt
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (q : PlanInvariant.PlanData
      (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) (s : Slot) (k : Coord) :
    (q.afterPrepareGroup A assignment).E s k =
      q.E s k + promotedAt A q s k := by
  unfold promotedAt
  cases hfirst : q.firstGroup A with
  | none => simp [PlanInvariant.PlanData.afterPrepareGroup, hfirst]
  | some g =>
      rcases g with ⟨headSlot, owner⟩
      by_cases hs : s = headSlot <;>
        simp [PlanInvariant.PlanData.afterPrepareGroup, hfirst, hs]

theorem promotedAt_add_target_B_le
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {q : PlanInvariant.PlanData
      (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : q.Valid A) (hrem : q.remaining.Nonempty)
    (assignment : Operation -> Option Claim) (s : Slot) (k : Coord) :
    promotedAt A q s k +
        (q.afterPrepareGroup A assignment).B
          (prepareState A (q.headGroup A) assignment) s k <=
      q.B A s k := by
  obtain ⟨g, hfirst⟩ := firstGroup_exists_of_remaining hv hrem
  rcases g with ⟨headSlot, owner⟩
  by_cases hs : s = headSlot
  · subst s
    have hbound := afterPrepareGroup_B_add_batchLoad_le
      (A := A) (p := q) assignment hfirst k
    simp [promotedAt, hfirst]
    omega
  · have hbound := afterPrepareGroup_B_le
      (A := A) (p := q) assignment s k
    simpa [promotedAt, hfirst, hs] using hbound

/-- Exact `B + E + W = P` preservation for owner-group Prepare with cleanup.
The withdrawal delta is the computed residual after both promoted demand and
the actual surviving target batch are removed from the source batch. -/
theorem afterPrepare_exact
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : FullPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.schedule.Valid A) (hrem : p.schedule.remaining.Nonempty)
    (hcoherent : Coherent A p) (hexact : p.ledger.ExactAccounting A)
    (assignment : Operation -> Option Claim) :
    (p.afterPrepare A assignment).ledger.ExactAccounting
      (prepareState A (p.schedule.headGroup A) assignment) := by
  let A' := prepareState A (p.schedule.headGroup A) assignment
  let q' := p.schedule.afterPrepareGroup A assignment
  have htargetCoherent := afterPrepare_coherent A p assignment
  intro s k
  have hOld := hexact s k
  have hSourceB := Coherent.ledger_B_eq_schedule_B hcoherent s k
  have hTargetB :
      (p.afterPrepare A assignment).ledger.B A' s k = q'.B A' s k := by
    simpa [A', q', afterPrepare] using
      (Coherent.ledger_B_eq_schedule_B htargetCoherent s k)
  have hSourceE : p.ledger.E s k = p.schedule.E s k := by
    exact congrFun (congrFun hcoherent.E_eq s) k
  have hSourceP : p.ledger.P s k = p.schedule.P s k := by
    exact congrFun (congrFun hcoherent.P_eq s) k
  have hTargetE := afterPrepare_E_eq_add_promotedAt
    A p.schedule assignment s k
  have hBound := promotedAt_add_target_B_le hv hrem assignment s k
  have hTargetP : q'.P s k = p.schedule.P s k := rfl
  rw [hTargetB]
  change q'.B A' s k + q'.E s k +
      (p.ledger.W s k + (p.ledger.B A s k -
        (promotedAt A p.schedule s k + q'.B A' s k))) = q'.P s k
  dsimp [A', q'] at hTargetE hBound hTargetP ⊢
  omega

end FullPlan

namespace FullState

def schedulerState
    (S : FullState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)) :
    PlanInvariant.PlanData.InvariantState
      (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) where
  lifecycle := S.lifecycle
  plan := S.plan.schedule

def afterPrepare
    (S : FullState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (assignment : Operation -> Option Claim) :
    FullState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) where
  lifecycle := prepareState S.lifecycle (S.plan.schedule.headGroup S.lifecycle)
    assignment
  plan := S.plan.afterPrepare S.lifecycle assignment

@[simp] theorem schedulerState_afterPrepare
    (S : FullState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (assignment : Operation -> Option Claim) :
    (S.afterPrepare assignment).schedulerState =
      PlanInvariant.PlanData.advancePrepare S.schedulerState assignment := rfl

/-- The combined controller projects to the existing authoritative rich-plan
Prepare relation. -/
theorem preparePlanned
    (S : FullState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (offered : Nat) (assignment : Operation -> Option Claim)
    (hWF : S.lifecycle.LWF) (hfull : FullInvariant S.lifecycle S.plan)
    (hrem : S.plan.schedule.remaining.Nonempty)
    (hVersion : S.plan.schedule.checkVersion offered = true)
    (hAssignment : Plan.checkAssignment S.lifecycle
      (S.plan.schedule.headGroup S.lifecycle) assignment = true) :
    PlanInvariant.PlanData.PreparePlanned S.schedulerState offered assignment
      (S.afterPrepare assignment).schedulerState := by
  rw [schedulerState_afterPrepare]
  exact PlanInvariant.PlanData.PreparePlanned.mk hWF hfull.schedule_valid hrem
    hVersion hAssignment

/-- Plan safety, representation coherence, and exact discrete accounting are
all reconstructed for the computed target. -/
theorem afterPrepare_preserves_full
    (S : FullState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (hfull : FullInvariant S.lifecycle S.plan)
    (hrem : S.plan.schedule.remaining.Nonempty)
    (assignment : Operation -> Option Claim) :
    FullInvariant (S.afterPrepare assignment).lifecycle
      (S.afterPrepare assignment).plan := by
  refine {
    schedule_valid := ?_
    coherent := ?_
    exact := ?_ }
  · simpa [FullState.afterPrepare, FullPlan.afterPrepare] using
      (PlanInvariant.PlanData.afterPrepareGroup_preserves_valid
        hfull.schedule_valid hrem assignment)
  · simpa [FullState.afterPrepare] using
      FullPlan.afterPrepare_coherent S.lifecycle S.plan assignment
  · simpa [FullState.afterPrepare] using
      FullPlan.afterPrepare_exact hfull.schedule_valid hrem hfull.coherent
        hfull.exact assignment

/-- End-to-end executable Prepare gate for the combined controller.  The
target ledger and its exact-accounting proof are conclusions, never inputs. -/
theorem checkedPrepare_preserves_full
    (S : FullState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (offered : Nat) (assignment : Operation -> Option Claim)
    (hWF : S.lifecycle.LWF) (hfull : FullInvariant S.lifecycle S.plan)
    (hrem : S.plan.schedule.remaining.Nonempty)
    (hVersion : S.plan.schedule.checkVersion offered = true)
    (hAssignment : Plan.checkAssignment S.lifecycle
      (S.plan.schedule.headGroup S.lifecycle) assignment = true) :
    PlanInvariant.PlanData.PreparePlanned S.schedulerState offered assignment
        (S.afterPrepare assignment).schedulerState ∧
      Step S.lifecycle .tau (S.afterPrepare assignment).lifecycle ∧
      FullInvariant (S.afterPrepare assignment).lifecycle
        (S.afterPrepare assignment).plan ∧
      (S.afterPrepare assignment).plan.schedule.version = offered + 1 ∧
      (S.afterPrepare assignment).plan.ledger.version = offered + 1 ∧
      (S.afterPrepare assignment).plan.schedule.remaining.card <
        S.plan.schedule.remaining.card := by
  have hplanned := preparePlanned S offered assignment hWF hfull hrem
    hVersion hAssignment
  have hOffered := PlanInvariant.PlanData.checkVersion_sound
    S.plan.schedule offered hVersion
  refine ⟨hplanned, hplanned.actual_step,
    afterPrepare_preserves_full S hfull hrem assignment, ?_, ?_, ?_⟩
  · simp [FullState.afterPrepare, FullPlan.afterPrepare,
      PlanInvariant.PlanData.afterPrepareGroup, hOffered]
  · simp [FullState.afterPrepare, FullPlan.afterPrepare,
      FullPlan.afterPrepareLedger, PlanInvariant.PlanData.afterPrepareGroup,
      hOffered]
  · exact hplanned.remaining_card_lt

end FullState

#print axioms FullPlan.afterPrepareLedger_remaining
#print axioms FullPlan.zeroDemand_source_leaf_visible
#print axioms FullPlan.afterPrepare_coherent
#print axioms FullPlan.afterPrepare_exact
#print axioms FullState.afterPrepare_preserves_full
#print axioms FullState.checkedPrepare_preserves_full

end AuthorityContinuity.FullPlanInvariant
