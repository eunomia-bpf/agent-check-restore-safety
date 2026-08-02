import AuthorityContinuity.Step

/-!
# Transportable authority plans

This module is the general, kernel-checked core of the Step 0007 experiment.
It deliberately separates the discrete lineage ledger from vector demand
accounting.  A zero-demand leaf is therefore still represented by its
`LeafDisposition`; vectors cannot silently erase it.

The positive grammar is intentionally narrower than the reviewed end state:
it contains checked canonical transfer, atomic current-head Prepare, ticket
steps, and checkpoint.  Same-slot Merge, restriction, and the complete
deadline scheduler remain separate proof obligations.
-/

namespace AuthorityContinuity.Plan

open AuthorityContinuity LifecycleState

universe uC uI uB uG uO uS

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO} {Slot : Type uS}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [DecidableEq Claim]
variable [Fintype Branch] [DecidableEq Branch]
variable [DecidableEq Grant] [Fintype Operation] [DecidableEq Operation]
variable [DecidableEq Slot]

/-! ## Computed transfer of a fixed claim batch -/

def transferFiber (tr : Transfer Claim Branch) (c : Claim) : Finset Claim :=
  Finset.univ.filter fun c' => tr.rho c' = some c

def childBatch (tr : Transfer Claim Branch) (U : Finset Claim) : Finset Claim :=
  Finset.univ.filter fun c' => ∃ c ∈ U, tr.rho c' = some c

def childRootSlot (root : Claim -> Option Slot)
    (tr : Transfer Claim Branch) (c' : Claim) : Option Slot :=
  (tr.rho c').bind root

def batchLoad
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (k : Coord) : Nat :=
  ∑ c ∈ U, A.auth.demand c k

def rootBatch (U : Finset Claim) (root : Claim -> Option Slot)
    (s : Slot) : Finset Claim :=
  U.filter fun c => root c = some s

def rootBatchLoad
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (root : Claim -> Option Slot)
    (s : Slot) (k : Coord) : Nat :=
  batchLoad A (rootBatch U root s) k

@[simp] theorem childRootSlot_of_rho
    (root : Claim -> Option Slot) (tr : Transfer Claim Branch)
    {c c' : Claim} (h : tr.rho c' = some c) :
    childRootSlot root tr c' = root c := by
  simp [childRootSlot, h]

theorem childBatch_root_inherited
    (tr : Transfer Claim Branch) (U : Finset Claim)
    (root : Claim -> Option Slot) {c' : Claim}
    (hc' : c' ∈ childBatch tr U) :
    ∃ c ∈ U, tr.rho c' = some c ∧
      childRootSlot root tr c' = root c := by
  obtain ⟨c, hc, hrho⟩ : ∃ c ∈ U, tr.rho c' = some c := by
    simpa [childBatch] using hc'
  exact ⟨c, hc, hrho, childRootSlot_of_rho root tr hrho⟩

theorem childBatch_eq_filter_image_some
    (tr : Transfer Claim Branch) (U : Finset Claim) :
    childBatch tr U =
      Finset.univ.filter fun c' => tr.rho c' ∈ U.image some := by
  ext c'
  simp only [childBatch, Finset.mem_filter, Finset.mem_univ, true_and]
  constructor
  · rintro ⟨c, hc, hrho⟩
    exact Finset.mem_image.mpr ⟨c, hc, hrho.symm⟩
  · intro hmem
    obtain ⟨c, hc, hrho⟩ := Finset.mem_image.mp hmem
    exact ⟨c, hc, hrho.symm⟩

/-- Arbitrary-batch conservation is derived from the actual checked
`Transfer.rho` fibers.  The target batch is not supplied by a caller. -/
theorem computed_batch_load_le
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (U : Finset Claim)
    (valid : Transfer.CoreValid A tr) (k : Coord) :
    batchLoad A (childBatch tr U) k <= batchLoad A U k := by
  let sourceOptions : Finset (Option Claim) := U.image some
  have hfiberwise :
      (∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' ∈ sourceOptions,
          A.auth.demand c' k) =
        ∑ source ∈ sourceOptions,
          ∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = source,
            A.auth.demand c' k := by
    simpa using (Finset.sum_fiberwise_eq_sum_filter
      Finset.univ sourceOptions tr.rho (fun c' => A.auth.demand c' k)).symm
  have hreindex :
      (∑ source ∈ sourceOptions,
          ∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = source,
            A.auth.demand c' k) =
        ∑ c ∈ U,
          ∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = some c,
            A.auth.demand c' k := by
    dsimp [sourceOptions]
    rw [Finset.sum_image]
    exact Option.some_injective Claim |>.injOn
  rw [childBatch_eq_filter_image_some]
  unfold batchLoad
  calc
    (∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' ∈ sourceOptions,
        A.auth.demand c' k) =
        ∑ source ∈ sourceOptions,
          ∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = source,
            A.auth.demand c' k := hfiberwise
    _ = ∑ c ∈ U,
          ∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = some c,
            A.auth.demand c' k := hreindex
    _ <= ∑ c ∈ U, A.auth.demand c k :=
      Finset.sum_le_sum fun c _ => valid.fiber_demand c k

@[simp] theorem childBatch_rootBatch
    (tr : Transfer Claim Branch) (U : Finset Claim)
    (root : Claim -> Option Slot) (s : Slot) :
    rootBatch (childBatch tr U) (childRootSlot root tr) s =
      childBatch tr (rootBatch U root s) := by
  ext c'
  simp only [rootBatch, childBatch, Finset.mem_filter, Finset.mem_univ,
    true_and]
  constructor
  · rintro ⟨⟨c, hc, hrho⟩, hroot⟩
    exact ⟨c, ⟨hc, by simpa [childRootSlot, hrho] using hroot⟩, hrho⟩
  · rintro ⟨c, ⟨hc, hroot⟩, hrho⟩
    exact ⟨⟨c, hc, hrho⟩, by simpa [childRootSlot, hrho] using hroot⟩

/-- Conservation holds independently in every immutable root slot. -/
theorem computed_root_batch_load_le
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (U : Finset Claim)
    (root : Claim -> Option Slot) (valid : Transfer.CoreValid A tr)
    (s : Slot) (k : Coord) :
    rootBatchLoad A (childBatch tr U) (childRootSlot root tr) s k <=
      rootBatchLoad A U root s k := by
  rw [rootBatchLoad, childBatch_rootBatch]
  exact computed_batch_load_le A tr (rootBatch U root s) valid k

/-! ## Discrete lineage and exact vector accounting -/

inductive LeafDisposition where
  | remaining
  | prepared
  | withdrawn
  deriving DecidableEq

/-- The classification is a partial function, so a leaf can never inhabit two
dispositions.  `none` denotes a superseded internal fragment, not an extant
leaf. -/
structure AuthorityPlan where
  version : Nat
  currentSlot : Slot
  disposition : Claim -> Option LeafDisposition
  leafRoot : Claim -> Option Slot
  R : Slot -> Coord -> Nat
  P : Slot -> Coord -> Nat
  E : Slot -> Coord -> Nat
  W : Slot -> Coord -> Nat

namespace AuthorityPlan

def leaves (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (d : LeafDisposition) : Finset Claim :=
  Finset.univ.filter fun c => p.disposition c = some d

def remaining
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    Finset Claim := p.leaves .remaining

def prepared
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    Finset Claim := p.leaves .prepared

def withdrawn
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    Finset Claim := p.leaves .withdrawn

def headGroup
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    Finset Claim := rootBatch p.remaining p.leafRoot p.currentSlot

def B
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (s : Slot) (k : Coord) : Nat :=
  rootBatchLoad A p.remaining p.leafRoot s k

/-- Exact componentwise accounting of current fragments (`B`), demand already
made durable by planned Prepare (`E`), and computed withdrawn demand (`W`). -/
def ExactAccounting
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)) : Prop :=
  ∀ s k, p.B A s k + p.E s k + p.W s k = p.P s k

def transferDisposition
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) (c : Claim) : Option LeafDisposition :=
  if c ∈ childBatch tr p.remaining then some .remaining
  else if c ∈ p.remaining then
    if transferFiber tr c = ∅ then some .withdrawn else none
  else p.disposition c

def transferLeafRoot
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) (c : Claim) : Option Slot :=
  if c ∈ childBatch tr p.remaining then childRootSlot p.leafRoot tr c
  else p.leafRoot c

/-- Every target field is computed from the source plan and actual `rho`.
The demand loss is derived only after comparing the actual target `B` with the
source `B`; neither target batch, root, nor `W` is an argument. -/
def afterTransfer
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot) :=
  let U' := childBatch tr p.remaining
  let root' := transferLeafRoot p tr
  { p with
    version := p.version + 1
    disposition := transferDisposition p tr
    leafRoot := root'
    W := fun s k => p.W s k +
      (p.B A s k - rootBatchLoad A U' root' s k) }

@[simp] theorem afterTransfer_remaining
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    (p.afterTransfer A tr).remaining = childBatch tr p.remaining := by
  ext c
  have hmem : c ∈ (p.afterTransfer A tr).remaining ↔
      (p.afterTransfer A tr).disposition c = some .remaining := by
    simp [remaining, leaves]
  rw [hmem]
  change transferDisposition p tr c = some .remaining ↔
    c ∈ childBatch tr p.remaining
  by_cases ht : c ∈ childBatch tr p.remaining
  · simp [afterTransfer, transferDisposition, ht]
  · by_cases ho : c ∈ p.remaining
    · have hd : p.disposition c = some .remaining := by
        simpa [remaining, leaves] using ho
      simp [afterTransfer, transferDisposition, ht, ho, hd]
    · have hd : p.disposition c ≠ some .remaining := by
        simpa [remaining, leaves] using ho
      simp [afterTransfer, transferDisposition, ht, ho, hd]

theorem afterTransfer_root_inherited
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    {c' : Claim} (hc' : c' ∈ (p.afterTransfer A tr).remaining) :
    ∃ c ∈ p.remaining, tr.rho c' = some c ∧
      (p.afterTransfer A tr).leafRoot c' = p.leafRoot c := by
  rw [afterTransfer_remaining] at hc'
  obtain ⟨c, hc, hrho, hroot⟩ :=
    childBatch_root_inherited tr p.remaining p.leafRoot hc'
  exact ⟨c, hc, hrho, by
    simp [afterTransfer, transferLeafRoot, hc', hroot]⟩

/-- A zero-demand child remains an explicit `remaining` leaf: membership is
independent of every demand coordinate. -/
theorem zero_demand_child_visible
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    {c' : Claim} (hc' : c' ∈ childBatch tr p.remaining)
    (_zero : ∀ k, A.auth.demand c' k = 0) :
    (p.afterTransfer A tr).disposition c' = some .remaining := by
  simp [afterTransfer, transferDisposition, hc']

/-- A source leaf with an empty actual fiber becomes explicitly withdrawn,
even when its demand vector is identically zero. -/
theorem empty_fiber_leaf_withdrawn
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    {c : Claim} (hc : c ∈ p.remaining)
    (hempty : transferFiber tr c = ∅)
    (hnotTarget : c ∉ childBatch tr p.remaining) :
    (p.afterTransfer A tr).disposition c = some .withdrawn := by
  simp [afterTransfer, transferDisposition, hc, hempty, hnotTarget]

theorem afterTransfer_B_le
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (valid : Transfer.CoreValid A tr) (s : Slot) (k : Coord) :
    (p.afterTransfer A tr).B A s k <= p.B A s k := by
  have hroots :
      rootBatch (childBatch tr p.remaining) (transferLeafRoot p tr) s =
        rootBatch (childBatch tr p.remaining)
          (childRootSlot p.leafRoot tr) s := by
    ext c
    constructor
    · intro hc
      have hm := (Finset.mem_filter.mp hc)
      exact Finset.mem_filter.mpr ⟨hm.1, by
        simpa [transferLeafRoot, hm.1] using hm.2⟩
    · intro hc
      have hm := (Finset.mem_filter.mp hc)
      exact Finset.mem_filter.mpr ⟨hm.1, by
        simpa [transferLeafRoot, hm.1] using hm.2⟩
  unfold B
  rw [afterTransfer_remaining]
  change rootBatchLoad A (childBatch tr p.remaining)
      (transferLeafRoot p tr) s k <= _
  rw [rootBatchLoad, hroots]
  exact computed_root_batch_load_le A tr p.remaining p.leafRoot valid s k

/-- `W' = W + (B-B')` is exact, not an adapter assertion. -/
theorem afterTransfer_exact
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (valid : Transfer.CoreValid A tr)
    (hexact : p.ExactAccounting A) :
    (p.afterTransfer A tr).ExactAccounting A := by
  intro s k
  have hle := p.afterTransfer_B_le A tr valid s k
  have hold := hexact s k
  have hnew :
      rootBatchLoad A (childBatch tr p.remaining) (transferLeafRoot p tr) s k =
        (p.afterTransfer A tr).B A s k := by
    unfold B
    rw [afterTransfer_remaining]
    rfl
  change (p.afterTransfer A tr).B A s k + p.E s k +
      (p.W s k + (p.B A s k -
        rootBatchLoad A (childBatch tr p.remaining)
          (transferLeafRoot p tr) s k)) = p.P s k
  rw [hnew]
  omega

end AuthorityPlan

/-! ## Atomic Prepare and actual lifecycle projection -/

def checkHead
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (offered : Nat) : Bool := decide (offered = p.version)

theorem checkHead_sound
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (offered : Nat) (h : checkHead p offered = true) :
    offered = p.version := by
  exact of_decide_eq_true (by simpa [checkHead] using h)

def checkAssignedMemberFresh
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation -> Option Claim) : Bool :=
  finiteAll Finset.univ fun e =>
    match assignment e with
    | none => true
    | some c => decide (c ∈ U ∧ A.opClaim e = none)

def checkAssignmentCovered (U : Finset Claim)
    (assignment : Operation -> Option Claim) : Bool :=
  finiteAll U fun c => decide (∃ e, assignment e = some c)

def checkAssignmentInjective
    (assignment : Operation -> Option Claim) : Bool :=
  finiteAll Finset.univ fun e =>
    finiteAll Finset.univ fun e' =>
      decide (∀ c, assignment e = some c ->
        assignment e' = some c -> e = e')

def checkAssignment
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation -> Option Claim) : Bool :=
  checkAssignedMemberFresh A U assignment &&
    (checkAssignmentCovered U assignment && checkAssignmentInjective assignment)

structure AssignmentValid
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation -> Option Claim) : Prop where
  assigned_mem : ∀ e c, assignment e = some c -> c ∈ U
  covered : ∀ c ∈ U, ∃ e, assignment e = some c
  assignment_injective : ∀ e e' c,
    assignment e = some c -> assignment e' = some c -> e = e'
  fresh : ∀ e c, assignment e = some c -> A.opClaim e = none

theorem checkAssignment_sound
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {U : Finset Claim} {assignment : Operation -> Option Claim}
    (hcheck : checkAssignment A U assignment = true) :
    AssignmentValid A U assignment := by
  have hp : checkAssignedMemberFresh A U assignment = true ∧
      checkAssignmentCovered U assignment = true ∧
      checkAssignmentInjective assignment = true := by
    simpa [checkAssignment, Bool.and_eq_true] using hcheck
  refine {
    assigned_mem := ?_
    covered := ?_
    assignment_injective := ?_
    fresh := ?_ }
  · intro e c he
    have hall := (finiteAll_eq_true Finset.univ _).mp hp.1 e
      (Finset.mem_univ e)
    have hpair : c ∈ U ∧ A.opClaim e = none := by
      simpa [checkAssignedMemberFresh, he] using hall
    exact hpair.1
  · intro c hc
    exact of_decide_eq_true ((finiteAll_eq_true U _).mp hp.2.1 c hc)
  · intro e e' c he he'
    have heall := (finiteAll_eq_true Finset.univ _).mp hp.2.2 e
      (Finset.mem_univ e)
    have he'all := (finiteAll_eq_true Finset.univ _).mp heall e'
      (Finset.mem_univ e')
    exact (of_decide_eq_true he'all) c he he'
  · intro e c he
    have hall := (finiteAll_eq_true Finset.univ _).mp hp.1 e
      (Finset.mem_univ e)
    exact (show c ∈ U ∧ A.opClaim e = none by
      simpa [checkAssignedMemberFresh, he] using hall).2

structure ControllerState where
  lifecycle : LifecycleState Coord Claim Branch Grant Operation
  plan : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)

namespace AuthorityPlan

def afterPrepare
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot) :=
  let U := p.headGroup
  { p with
    version := p.version + 1
    disposition := fun c => if c ∈ U then some .prepared else p.disposition c
    E := fun s k => if s = p.currentSlot
      then p.E s k + batchLoad A U k else p.E s k }

@[simp] theorem afterPrepare_remaining
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    (p.afterPrepare A).remaining = p.remaining \ p.headGroup := by
  ext c
  simp only [remaining, leaves, Finset.mem_filter, Finset.mem_univ, true_and,
    Finset.mem_sdiff]
  by_cases hu : c ∈ p.headGroup
  · simp [afterPrepare, hu]
  · simp [afterPrepare, hu]

theorem afterPrepare_exact
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : AuthorityPlan (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim)
    (hexact : p.ExactAccounting A) :
    (p.afterPrepare A).ExactAccounting
      (prepareState A p.headGroup assignment) := by
  intro s k
  by_cases hs : s = p.currentSlot
  · subst s
    have hold := hexact p.currentSlot k
    have hcurset :
        rootBatch (p.remaining \ p.headGroup) p.leafRoot p.currentSlot = ∅ := by
      ext c
      constructor
      · intro hc
        have hf := Finset.mem_filter.mp hc
        have hd := Finset.mem_sdiff.mp hf.1
        exfalso
        apply hd.2
        change c ∈ rootBatch p.remaining p.leafRoot p.currentSlot
        exact Finset.mem_filter.mpr ⟨hd.1, hf.2⟩
      · intro hc
        simpa using hc
    have hzero :
        (p.afterPrepare A).B (prepareState A p.headGroup assignment)
          p.currentSlot k = 0 := by
      unfold B
      rw [afterPrepare_remaining]
      change rootBatchLoad (prepareState A p.headGroup assignment)
        (p.remaining \ p.headGroup) p.leafRoot p.currentSlot k = 0
      rw [rootBatchLoad, hcurset]
      simp [batchLoad]
    have hhead : batchLoad A p.headGroup k = p.B A p.currentSlot k := rfl
    rw [hzero]
    simp only [afterPrepare, if_pos]
    rw [hhead]
    omega
  · have hold := hexact s k
    have hsome : (some s : Option Slot) ≠ some p.currentSlot := by
      intro h
      exact hs (Option.some.inj h)
    have hotherset :
        rootBatch (p.remaining \ p.headGroup) p.leafRoot s =
          rootBatch p.remaining p.leafRoot s := by
      ext c
      constructor
      · intro hc
        have hf := Finset.mem_filter.mp hc
        have hd := Finset.mem_sdiff.mp hf.1
        exact Finset.mem_filter.mpr ⟨hd.1, hf.2⟩
      · intro hc
        have hf := Finset.mem_filter.mp hc
        apply Finset.mem_filter.mpr
        refine ⟨Finset.mem_sdiff.mpr ⟨hf.1, ?_⟩, hf.2⟩
        intro hhead
        change c ∈ rootBatch p.remaining p.leafRoot p.currentSlot at hhead
        have hh := (Finset.mem_filter.mp hhead).2
        exact hsome (hf.2.symm.trans hh)
    have hsame :
        (p.afterPrepare A).B (prepareState A p.headGroup assignment) s k =
          p.B A s k := by
      unfold B
      rw [afterPrepare_remaining]
      change rootBatchLoad (prepareState A p.headGroup assignment)
        (p.remaining \ p.headGroup) p.leafRoot s k = p.B A s k
      rw [rootBatchLoad, hotherset]
      rfl
    rw [hsame]
    simp only [afterPrepare, if_neg hs]
    exact hold

end AuthorityPlan

def preparedController (S : ControllerState (Coord := Coord) (Claim := Claim)
    (Branch := Branch) (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (assignment : Operation -> Option Claim) :
    ControllerState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) where
  lifecycle := prepareState S.lifecycle S.plan.headGroup assignment
  plan := S.plan.afterPrepare S.lifecycle

theorem prepare_head_is_ok
    (S : ControllerState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (offered : Nat) (assignment : Operation -> Option Claim)
    (hWF : S.lifecycle.LWF)
    (hHead : checkHead S.plan offered = true)
    (hAssignment : checkAssignment S.lifecycle S.plan.headGroup assignment = true)
    (hne : S.plan.headGroup.Nonempty)
    (htentative : ∀ c ∈ S.plan.headGroup, ∃ b,
      S.lifecycle.auth.status c = .tentative b)
    (hbatchP : ∀ k, batchLoad S.lifecycle S.plan.headGroup k <=
      S.plan.P S.plan.currentSlot k)
    (hPfits : ∀ k, S.lifecycle.auth.durableLoad k +
      S.plan.P S.plan.currentSlot k <= S.lifecycle.auth.capacity k) :
    offered = S.plan.version ∧
      PrepareOK S.lifecycle S.plan.headGroup assignment := by
  have ha := checkAssignment_sound hAssignment
  refine ⟨checkHead_sound S.plan offered hHead, {
    nonempty := hne
    member_open := ?_
    base := ?_
    assigned_mem := ha.assigned_mem
    covered := ha.covered
    assignment_injective := ha.assignment_injective
    fresh := ha.fresh }⟩
  · intro c hc
    obtain ⟨b, hs⟩ := htentative c hc
    exact ⟨b, hs, hWF.owner_open c b hs, hWF.grant_open c b hs⟩
  · intro k
    calc
      promotedLoad S.lifecycle.auth S.plan.headGroup k =
          S.lifecycle.auth.durableLoad k +
            batchLoad S.lifecycle S.plan.headGroup k := rfl
      _ <= S.lifecycle.auth.durableLoad k +
            S.plan.P S.plan.currentSlot k :=
        Nat.add_le_add_left (hbatchP k) _
      _ <= S.lifecycle.auth.capacity k := hPfits k

inductive PreparePlanned :
    ControllerState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) ->
    Nat -> (Operation -> Option Claim) ->
    ControllerState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) -> Prop where
  | mk {S offered assignment}
      (hWF : S.lifecycle.LWF)
      (hHead : checkHead S.plan offered = true)
      (hAssignment :
        checkAssignment S.lifecycle S.plan.headGroup assignment = true)
      (hne : S.plan.headGroup.Nonempty)
      (htentative : ∀ c ∈ S.plan.headGroup, ∃ b,
        S.lifecycle.auth.status c = .tentative b)
      (hbatchP : ∀ k, batchLoad S.lifecycle S.plan.headGroup k <=
        S.plan.P S.plan.currentSlot k)
      (hPfits : ∀ k, S.lifecycle.auth.durableLoad k +
        S.plan.P S.plan.currentSlot k <= S.lifecycle.auth.capacity k) :
      PreparePlanned S offered assignment (preparedController S assignment)

theorem PreparePlanned.actual_step
    {S S' : ControllerState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)}
    {offered : Nat} {assignment : Operation -> Option Claim}
    (h : PreparePlanned S offered assignment S') :
    Step S.lifecycle .tau S'.lifecycle := by
  cases h with
  | mk hWF hHead hAssignment hne htentative hbatchP hPfits =>
      have hOK := (prepare_head_is_ok S offered assignment hWF hHead
        hAssignment hne htentative hbatchP hPfits).2
      simpa [preparedController] using Step.core (CoreStep.prepare hOK)

theorem PreparePlanned.accounting
    {S S' : ControllerState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)}
    {offered : Nat} {assignment : Operation -> Option Claim}
    (h : PreparePlanned S offered assignment S')
    (hexact : S.plan.ExactAccounting S.lifecycle) :
    S'.plan.ExactAccounting S'.lifecycle := by
  cases h
  simpa [preparedController] using
    (AuthorityPlan.afterPrepare_exact S.lifecycle S.plan assignment hexact)

def canonicalController
    (S : ControllerState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) :
    ControllerState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) where
  lifecycle := canonicalTarget S.lifecycle tr op
  plan := S.plan.afterTransfer S.lifecycle tr

inductive PlannedStep :
    ControllerState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) ->
    Label Operation Claim ->
    ControllerState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) -> Prop where
  | checkpoint (S) : PlannedStep S .tau S
  | canonical (S) (offered : Nat)
      (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
      (headChecked : checkHead S.plan offered = true)
      (checked : checkCanonical S.lifecycle tr op = true) :
      PlannedStep S .tau (canonicalController S tr op)
  | prepare {S S' offered assignment}
      (h : PreparePlanned S offered assignment S') : PlannedStep S .tau S'
  | ticket (S) {A' : LifecycleState Coord Claim Branch Grant Operation}
      {eta : Label Operation Claim} (h : TicketStep S.lifecycle eta A') :
      PlannedStep S eta { lifecycle := A', plan := S.plan }

theorem PlannedStep.actual_step
    {S S' : ControllerState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)}
    {eta : Label Operation Claim} (h : PlannedStep S eta S') :
    Step S.lifecycle eta S'.lifecycle := by
  cases h with
  | checkpoint => exact Step.core (CoreStep.checkpoint _)
  | canonical offered tr op headChecked checked =>
      exact Step.canonical tr op checked
  | prepare h => exact h.actual_step
  | ticket h => exact Step.core (CoreStep.ticket h)

theorem PlannedStep.preserves_accounting
    {S S' : ControllerState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)}
    {eta : Label Operation Claim} (h : PlannedStep S eta S')
    (hexact : S.plan.ExactAccounting S.lifecycle) :
    S'.plan.ExactAccounting S'.lifecycle := by
  cases h with
  | checkpoint => exact hexact
  | canonical offered tr op headChecked checked =>
      have hv := (checkCanonical_sound S.lifecycle tr op checked).transfer.toCoreValid
      have ht := S.plan.afterTransfer_exact S.lifecycle tr hv hexact
      simpa [canonicalController, AuthorityPlan.ExactAccounting,
        AuthorityPlan.B, rootBatchLoad, batchLoad, canonicalTarget,
        Transfer.targetCore] using ht
  | prepare h => exact h.accounting hexact
  | ticket h =>
      have hauth := ticketStep_auth_eq h
      simpa [AuthorityPlan.ExactAccounting, AuthorityPlan.B, rootBatchLoad,
        batchLoad, hauth] using hexact

def PlannedAbstractStep
    (S S' : ControllerState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)) : Prop :=
  ∃ eta, PlannedStep S eta S'

abbrev PlannedTrace
    (S S' : ControllerState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)) : Prop :=
  Relation.ReflTransGen PlannedAbstractStep S S'

/-- Arbitrary finite positive histories preserve the base lifecycle invariants
and the exact `B/E/W=P` authority-plan accounting. -/
theorem planned_trace_preserves
    {S S' : ControllerState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    (htrace : PlannedTrace S S')
    (hWF : S.lifecycle.LWF) (hAC : AC S.lifecycle.auth)
    (hActive : S.lifecycle.ActiveExact)
    (hexact : S.plan.ExactAccounting S.lifecycle) :
    S'.lifecycle.LWF ∧ AC S'.lifecycle.auth ∧
      S'.lifecycle.ActiveExact ∧ S'.plan.ExactAccounting S'.lifecycle := by
  induction htrace with
  | refl => exact ⟨hWF, hAC, hActive, hexact⟩
  | tail _ hstep ih =>
      obtain ⟨eta, hplanned⟩ := hstep
      have hbase := step_preserves_wf_ac hplanned.actual_step
        ih.1 ih.2.1 ih.2.2.1
      exact ⟨hbase.1, hbase.2.1, hbase.2.2,
        hplanned.preserves_accounting ih.2.2.2⟩

/-- Every planned trace erases to a trace of the repository's sole actual
lifecycle relation. -/
theorem planned_trace_projects
    {S S' : ControllerState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    (htrace : PlannedTrace S S') :
    Relation.ReflTransGen
      (fun A A' : LifecycleState Coord Claim Branch Grant Operation =>
        ∃ eta, Step A eta A') S.lifecycle S'.lifecycle := by
  induction htrace with
  | refl => exact .refl
  | tail _ hstep ih =>
      obtain ⟨eta, hplanned⟩ := hstep
      exact ih.tail ⟨eta, hplanned.actual_step⟩

#print axioms computed_batch_load_le
#print axioms computed_root_batch_load_le
#print axioms AuthorityPlan.afterTransfer_exact
#print axioms prepare_head_is_ok
#print axioms PreparePlanned.actual_step
#print axioms planned_trace_preserves
#print axioms planned_trace_projects

end AuthorityContinuity.Plan
