import AuthorityContinuity.Transfer
import Mathlib.Data.Finset.Powerset

/-!
# Computed canonical history transformations

This module gives the four canonical topology operations an exact finite
semantics.  In contrast with the former fieldwise target certificate, neither the
target contract nor any of its well-formedness fields is supplied by the
caller: the target branch support, contract, and epoch map are computed from
the operation and the source state.
-/

namespace AuthorityContinuity

universe uC uI uB uG uO

/-- The four topology operations whose contracts have a canonical preimage
semantics.  Merge is deliberately separate because its target is explicit. -/
inductive CanonicalOp (Branch : Type uB) where
  | choiceFork (parent left right : Branch)
  | parallelFork (parent left right : Branch)
  | replaceRestore (parent restored : Branch)
  | liveRestore (parent restored : Branch)
  deriving DecidableEq, Repr

namespace CanonicalOp

variable {Branch : Type uB} [Fintype Branch] [DecidableEq Branch]

/-- The source lineage collapsed by a canonical operation. -/
def parent : CanonicalOp Branch -> Branch
  | .choiceFork b _ _ | .parallelFork b _ _
  | .replaceRestore b _ | .liveRestore b _ => b

/-- Target lineages that project to the source parent. -/
def descendants : CanonicalOp Branch -> Finset Branch
  | .choiceFork _ b0 b1 | .parallelFork _ b0 b1 => {b0, b1}
  | .replaceRestore _ b' => {b'}
  | .liveRestore b b' => {b, b'}

/-- Branch epochs newly opened by the operation. -/
def fresh : CanonicalOp Branch -> Finset Branch
  | .choiceFork _ b0 b1 | .parallelFork _ b0 b1 => {b0, b1}
  | .replaceRestore _ b' | .liveRestore _ b' => {b'}

/-- Whether the source parent is retired. -/
def retiresParent : CanonicalOp Branch -> Bool
  | .choiceFork .. | .parallelFork .. | .replaceRestore .. => true
  | .liveRestore .. => false

/-- Choice is the only canonical form that excludes simultaneous descendants. -/
def exclusive : CanonicalOp Branch -> Bool
  | .choiceFork .. => true
  | _ => false

/-- Number of genuinely fresh branch IDs required by the operation. -/
def freshArity : CanonicalOp Branch -> Nat
  | .choiceFork .. | .parallelFork .. => 2
  | .replaceRestore .. | .liveRestore .. => 1

/-- Replace the source parent in an active set by the operation's descendants. -/
def targetActive (op : CanonicalOp Branch) (source : Finset Branch) :
    Finset Branch :=
  if op.retiresParent then (source.erase op.parent) ∪ op.descendants
  else source ∪ op.descendants

/-- Collapse any nonempty set of descendants to the source parent while
preserving every unrelated branch. -/
def project (op : CanonicalOp Branch) (C : Finset Branch) : Finset Branch :=
  let context := C \ op.descendants
  if Disjoint C op.descendants then context else insert op.parent context

/-- Operation-local epoch freshness and distinctness.  This checker observes
only the source epoch map; it does not inspect a computed target invariant. -/
def checkFresh
    {Coord : Type uC} {Claim : Type uI} {Grant : Type uG}
    {Operation : Type uO}
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (op : CanonicalOp Branch) : Bool :=
  let freshOK := finiteAll op.fresh fun b => decide (A.branchEpoch b = .unissued)
  let parentOpen := decide (A.branchEpoch op.parent = .open)
  let distinct := decide (op.parent ∉ op.fresh) && decide (op.fresh.card =
    op.freshArity)
  freshOK && parentOpen && distinct

/-- Semantic facts emitted by `checkFresh`.  This record is checker output,
not an operation premise chosen by a caller. -/
structure FreshValid
    {Coord : Type uC} {Claim : Type uI} {Grant : Type uG}
    {Operation : Type uO}
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (op : CanonicalOp Branch) : Prop where
  fresh_unissued : ∀ b ∈ op.fresh, A.branchEpoch b = .unissued
  parent_open : A.branchEpoch op.parent = .open
  parent_not_fresh : op.parent ∉ op.fresh
  fresh_card : op.fresh.card = op.freshArity

/-- Soundness of the operation-local freshness checker. -/
theorem checkFresh_sound
    {Coord : Type uC} {Claim : Type uI} {Grant : Type uG}
    {Operation : Type uO}
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (op : CanonicalOp Branch) (hcheck : checkFresh A op = true) :
    FreshValid A op := by
  simp only [checkFresh, Bool.and_eq_true, decide_eq_true_eq] at hcheck
  rcases hcheck with ⟨⟨hfresh, hopen⟩, hnot, hcard⟩
  refine ⟨?_, hopen, hnot, hcard⟩
  intro b hb
  exact of_decide_eq_true
    ((finiteAll_eq_true op.fresh _).mp hfresh b hb)

/-- Exact target epoch update.  No closed epoch can reopen because every newly
opened epoch must pass `checkFresh`. -/
def targetEpoch
    {Coord : Type uC} {Claim : Type uI} {Grant : Type uG}
    {Operation : Type uO}
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (op : CanonicalOp Branch) (b : Branch) : EpochStatus :=
  if b ∈ op.fresh then .open
  else if op.retiresParent && b = op.parent then .closed
  else A.branchEpoch b

end CanonicalOp

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [DecidableEq Claim]
variable [Fintype Branch] [DecidableEq Branch]
variable [DecidableEq Grant] [DecidableEq Operation]

/-- Extensional support of the finite contract. -/
def contractSupport (allowed : Finset (Finset Branch)) : Finset Branch :=
  allowed.biUnion id

/-- Exact allowed family generated by a canonical operation. -/
def canonicalAllowed
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (op : CanonicalOp Branch) : Finset (Finset Branch) :=
  Finset.univ.powerset.filter fun C =>
    decide (C ⊆ op.targetActive (contractSupport A.auth.allowed)) &&
    decide (op.project C ∈ A.auth.allowed) &&
    (if op.exclusive then decide ((C ∩ op.descendants).card ≤ 1) else true)

@[simp] theorem mem_contractSupport_iff
    (allowed : Finset (Finset Branch)) (b : Branch) :
    b ∈ contractSupport allowed ↔ ∃ C ∈ allowed, b ∈ C := by
  simp [contractSupport]

@[simp] theorem mem_canonicalAllowed_iff
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (op : CanonicalOp Branch) (C : Finset Branch) :
    C ∈ canonicalAllowed A op ↔
      C ⊆ op.targetActive (contractSupport A.auth.allowed) ∧
      op.project C ∈ A.auth.allowed ∧
      (op.exclusive = true → (C ∩ op.descendants).card ≤ 1) := by
  simp only [canonicalAllowed, Finset.mem_filter, Finset.mem_powerset,
    Finset.subset_univ, true_and, Bool.and_eq_true, decide_eq_true_eq]
  by_cases h : op.exclusive = true
  · simp [h, and_assoc]
  · have hf : op.exclusive = false := Bool.eq_false_of_not_eq_true h
    simp [hf, h]

/-- Canonical projection preserves the empty configuration by construction. -/
theorem canonicalProjection_zero (op : CanonicalOp Branch) :
    op.project ∅ = ∅ := by
  simp [CanonicalOp.project]

/-- Canonical projection is monotone. -/
theorem canonicalProjection_mono (op : CanonicalOp Branch) :
    Monotone op.project := by
  intro C D hCD
  intro x hx
  unfold CanonicalOp.project at hx ⊢
  by_cases hC : Disjoint C op.descendants
  · have hDcontext : C \ op.descendants ⊆ D \ op.descendants := by
      intro y hy
      exact Finset.mem_sdiff.mpr
        ⟨hCD (Finset.mem_sdiff.mp hy).1, (Finset.mem_sdiff.mp hy).2⟩
    by_cases hD : Disjoint D op.descendants
    · simpa [hC, hD] using hDcontext (by simpa [hC] using hx)
    · simp only [hD, if_false, Finset.mem_insert]
      exact Or.inr (hDcontext (by simpa [hC] using hx))
  · have hD : ¬ Disjoint D op.descendants := by
      intro hd
      apply hC
      rw [Finset.disjoint_left] at hd ⊢
      intro y hyC hyDesc
      exact hd (hCD hyC) hyDesc
    simp only [hC, hD, if_false, Finset.mem_insert] at hx ⊢
    rcases hx with rfl | hx
    · exact Or.inl rfl
    · exact Or.inr (Finset.mem_sdiff.mpr
        ⟨hCD (Finset.mem_sdiff.mp hx).1, (Finset.mem_sdiff.mp hx).2⟩)

theorem canonicalProjection_singleton_of_mem
    (op : CanonicalOp Branch) {b : Branch} (hb : b ∈ op.descendants) :
    op.project {b} = {op.parent} := by
  have hsubset : {b} ⊆ op.descendants := by simpa
  unfold CanonicalOp.project
  rw [Finset.sdiff_eq_empty_iff_subset.mpr hsubset]
  simp [hb, Finset.disjoint_left]

theorem canonicalProjection_singleton_of_not_mem
    (op : CanonicalOp Branch) {b : Branch} (hb : b ∉ op.descendants) :
    op.project {b} = {b} := by
  simp [CanonicalOp.project, hb, Finset.disjoint_left]

/-- Downward closure turns extensional support into singleton membership. -/
theorem singleton_allowed_of_support
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (hWF : WF A.auth) {b : Branch}
    (hb : b ∈ contractSupport A.auth.allowed) : {b} ∈ A.auth.allowed := by
  obtain ⟨C, hC, hbC⟩ := (mem_contractSupport_iff A.auth.allowed b).1 hb
  apply hWF.downward hC
  exact Finset.singleton_subset_iff.mpr hbC

/-- The exact preimage family has exactly the computed active support.  The
reverse inclusion is constructive: each active target branch has an admitted
singleton, collapsed either to itself or to the supported source parent. -/
theorem contractSupport_canonicalAllowed_eq
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (op : CanonicalOp Branch) (hWF : WF A.auth)
    (hActive : LifecycleState.ActiveExact A)
    (hFresh : CanonicalOp.FreshValid A op) :
    contractSupport (canonicalAllowed A op) =
      op.targetActive (contractSupport A.auth.allowed) := by
  apply Finset.Subset.antisymm
  · intro b hb
    obtain ⟨C, hC, hbC⟩ :=
      (mem_contractSupport_iff (canonicalAllowed A op) b).1 hb
    exact ((mem_canonicalAllowed_iff A op C).1 hC).1 hbC
  · intro b hb
    rw [mem_contractSupport_iff]
    refine ⟨{b}, ?_, by simp⟩
    rw [mem_canonicalAllowed_iff]
    refine ⟨by simpa using hb, ?_, ?_⟩
    · by_cases hdesc : b ∈ op.descendants
      · rw [canonicalProjection_singleton_of_mem op hdesc]
        apply singleton_allowed_of_support A hWF
        exact (mem_contractSupport_iff A.auth.allowed op.parent).2
          ((hActive op.parent).1 hFresh.parent_open)
      · rw [canonicalProjection_singleton_of_not_mem op hdesc]
        apply singleton_allowed_of_support A hWF
        cases op with
        | choiceFork parent left right =>
            have hmem : b ∈ (contractSupport A.auth.allowed).erase parent ∪
                {left, right} := by
              simpa [CanonicalOp.targetActive, CanonicalOp.retiresParent,
                CanonicalOp.descendants] using hb
            have hnot : b ∉ ({left, right} : Finset Branch) := by
              simpa [CanonicalOp.descendants] using hdesc
            exact (Finset.mem_erase.mp
              ((Finset.mem_union.mp hmem).resolve_right hnot)).2
        | parallelFork parent left right =>
            have hmem : b ∈ (contractSupport A.auth.allowed).erase parent ∪
                {left, right} := by
              simpa [CanonicalOp.targetActive, CanonicalOp.retiresParent,
                CanonicalOp.descendants] using hb
            have hnot : b ∉ ({left, right} : Finset Branch) := by
              simpa [CanonicalOp.descendants] using hdesc
            exact (Finset.mem_erase.mp
              ((Finset.mem_union.mp hmem).resolve_right hnot)).2
        | replaceRestore parent restored =>
            have hmem : b ∈ (contractSupport A.auth.allowed).erase parent ∪
                {restored} := by
              simpa [CanonicalOp.targetActive, CanonicalOp.retiresParent,
                CanonicalOp.descendants] using hb
            have hnot : b ∉ ({restored} : Finset Branch) := by
              simpa [CanonicalOp.descendants] using hdesc
            exact (Finset.mem_erase.mp
              ((Finset.mem_union.mp hmem).resolve_right hnot)).2
        | liveRestore parent restored =>
            have hmem : b ∈ contractSupport A.auth.allowed ∪
                {parent, restored} := by
              simpa [CanonicalOp.targetActive, CanonicalOp.retiresParent,
                CanonicalOp.descendants] using hb
            have hnot : b ∉ ({parent, restored} : Finset Branch) := by
              simpa [CanonicalOp.descendants] using hdesc
            exact (Finset.mem_union.mp hmem).resolve_right hnot
    · intro _
      have hcard := Finset.card_le_card
        (show {b} ∩ op.descendants ⊆ {b} from Finset.inter_subset_left)
      simpa using hcard

/-- The computed epoch update opens exactly the computed target support. -/
theorem canonicalTargetEpoch_open_iff
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (op : CanonicalOp Branch)
    (hActive : LifecycleState.ActiveExact A)
    (hFresh : CanonicalOp.FreshValid A op) (b : Branch) :
    op.targetEpoch A b = .open ↔
      b ∈ op.targetActive (contractSupport A.auth.allowed) := by
  cases op with
  | choiceFork parent left right =>
      have hpnot : parent ∉ ({left, right} : Finset Branch) := by
        simpa [CanonicalOp.parent, CanonicalOp.fresh] using
          hFresh.parent_not_fresh
      by_cases hchild : b ∈ ({left, right} : Finset Branch)
      · simp_all [CanonicalOp.targetEpoch, CanonicalOp.fresh,
          CanonicalOp.targetActive, CanonicalOp.retiresParent,
          CanonicalOp.parent, CanonicalOp.descendants]
        exact hchild.elim Or.inl (fun hr => Or.inr (Or.inl hr))
      · by_cases hparent : b = parent
        · subst b
          simp_all [CanonicalOp.targetEpoch, CanonicalOp.fresh,
            CanonicalOp.targetActive, CanonicalOp.retiresParent,
            CanonicalOp.parent, CanonicalOp.descendants]
        · have hsource : A.branchEpoch b = .open ↔
              b ∈ contractSupport A.auth.allowed := by
            rw [hActive b, mem_contractSupport_iff]
          simp_all [CanonicalOp.targetEpoch, CanonicalOp.fresh,
            CanonicalOp.targetActive, CanonicalOp.retiresParent,
            CanonicalOp.parent, CanonicalOp.descendants]
  | parallelFork parent left right =>
      have hpnot : parent ∉ ({left, right} : Finset Branch) := by
        simpa [CanonicalOp.parent, CanonicalOp.fresh] using
          hFresh.parent_not_fresh
      by_cases hchild : b ∈ ({left, right} : Finset Branch)
      · simp_all [CanonicalOp.targetEpoch, CanonicalOp.fresh,
          CanonicalOp.targetActive, CanonicalOp.retiresParent,
          CanonicalOp.parent, CanonicalOp.descendants]
        exact hchild.elim Or.inl (fun hr => Or.inr (Or.inl hr))
      · by_cases hparent : b = parent
        · subst b
          simp_all [CanonicalOp.targetEpoch, CanonicalOp.fresh,
            CanonicalOp.targetActive, CanonicalOp.retiresParent,
            CanonicalOp.parent, CanonicalOp.descendants]
        · have hsource : A.branchEpoch b = .open ↔
              b ∈ contractSupport A.auth.allowed := by
            rw [hActive b, mem_contractSupport_iff]
          simp_all [CanonicalOp.targetEpoch, CanonicalOp.fresh,
            CanonicalOp.targetActive, CanonicalOp.retiresParent,
            CanonicalOp.parent, CanonicalOp.descendants]
  | replaceRestore parent restored =>
      have hpnot : parent ∉ ({restored} : Finset Branch) := by
        simpa [CanonicalOp.parent, CanonicalOp.fresh] using
          hFresh.parent_not_fresh
      by_cases hchild : b ∈ ({restored} : Finset Branch)
      · simp_all [CanonicalOp.targetEpoch, CanonicalOp.fresh,
          CanonicalOp.targetActive, CanonicalOp.retiresParent,
          CanonicalOp.parent, CanonicalOp.descendants]
      · by_cases hparent : b = parent
        · subst b
          simp_all [CanonicalOp.targetEpoch, CanonicalOp.fresh,
            CanonicalOp.targetActive, CanonicalOp.retiresParent,
            CanonicalOp.parent, CanonicalOp.descendants]
        · have hsource : A.branchEpoch b = .open ↔
              b ∈ contractSupport A.auth.allowed := by
            rw [hActive b, mem_contractSupport_iff]
          simp_all [CanonicalOp.targetEpoch, CanonicalOp.fresh,
            CanonicalOp.targetActive, CanonicalOp.retiresParent,
            CanonicalOp.parent, CanonicalOp.descendants]
  | liveRestore parent restored =>
      have hpSupport : parent ∈ contractSupport A.auth.allowed :=
        (mem_contractSupport_iff A.auth.allowed parent).2
          ((hActive parent).1 hFresh.parent_open)
      by_cases hnew : b = restored
      · subst b
        simp_all [CanonicalOp.targetEpoch, CanonicalOp.fresh,
          CanonicalOp.targetActive, CanonicalOp.retiresParent,
          CanonicalOp.parent, CanonicalOp.descendants]
      · have hsource : A.branchEpoch b = .open ↔
            b ∈ contractSupport A.auth.allowed := by
          rw [hActive b, mem_contractSupport_iff]
        simp_all [CanonicalOp.targetEpoch, CanonicalOp.fresh,
          CanonicalOp.targetActive, CanonicalOp.retiresParent,
          CanonicalOp.parent, CanonicalOp.descendants]

/-- Choice membership is exactly pulled-back source membership, active target
support, and child exclusivity. -/
theorem choiceFork_allowed_iff
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (b b0 b1 : Branch) (C : Finset Branch) :
    C ∈ canonicalAllowed A (.choiceFork b b0 b1) ↔
      C ⊆ (contractSupport A.auth.allowed).erase b ∪ {b0, b1} ∧
      (CanonicalOp.choiceFork b b0 b1).project C ∈ A.auth.allowed ∧
      (C ∩ {b0, b1}).card ≤ 1 := by
  simp [mem_canonicalAllowed_iff, CanonicalOp.targetActive,
    CanonicalOp.retiresParent, CanonicalOp.parent, CanonicalOp.descendants,
    CanonicalOp.exclusive]

/-- Parallel membership is the unrestricted pulled-back preimage over the
computed active target, including the jointly-present child case. -/
theorem parallelFork_allowed_iff
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (b b0 b1 : Branch) (C : Finset Branch) :
    C ∈ canonicalAllowed A (.parallelFork b b0 b1) ↔
      C ⊆ (contractSupport A.auth.allowed).erase b ∪ {b0, b1} ∧
      (CanonicalOp.parallelFork b b0 b1).project C ∈ A.auth.allowed := by
  simp [mem_canonicalAllowed_iff, CanonicalOp.targetActive,
    CanonicalOp.retiresParent, CanonicalOp.parent, CanonicalOp.descendants,
    CanonicalOp.exclusive]

/-- Replacing restore is the exact contextual alpha-replacement preimage. -/
theorem replaceRestore_allowed_iff
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (b b' : Branch) (C : Finset Branch) :
    C ∈ canonicalAllowed A (.replaceRestore b b') ↔
      C ⊆ (contractSupport A.auth.allowed).erase b ∪ {b'} ∧
      (CanonicalOp.replaceRestore b b').project C ∈ A.auth.allowed := by
  simp [mem_canonicalAllowed_iff, CanonicalOp.targetActive,
    CanonicalOp.retiresParent, CanonicalOp.parent, CanonicalOp.descendants,
    CanonicalOp.exclusive]

/-- Live restore is the exact contextual preimage in which the old and new
lineages may occur separately or together. -/
theorem liveRestore_allowed_iff
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (b b' : Branch) (C : Finset Branch) :
    C ∈ canonicalAllowed A (.liveRestore b b') ↔
      C ⊆ contractSupport A.auth.allowed ∪ {b, b'} ∧
      (CanonicalOp.liveRestore b b').project C ∈ A.auth.allowed := by
  simp [mem_canonicalAllowed_iff, CanonicalOp.targetActive,
    CanonicalOp.retiresParent, CanonicalOp.parent, CanonicalOp.descendants,
    CanonicalOp.exclusive]

/-- The target owner of every transferred claim must be one of the branches
computed by the canonical builder.  This local atom rules out, for example,
leaving a claim on a parent retired by replace restore.  It does not inspect
the target contract or any target invariant. -/
def checkCanonicalOwnerActive
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) : Bool :=
  finiteAll Finset.univ fun c =>
    match tr.owner c with
    | none => true
    | some b => decide
        (b ∈ op.targetActive (contractSupport A.auth.allowed))

theorem checkCanonicalOwnerActive_sound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (hcheck : checkCanonicalOwnerActive A tr op = true) :
    ∀ c b, tr.owner c = some b →
      b ∈ op.targetActive (contractSupport A.auth.allowed) := by
  intro c b howner
  have hc := (finiteAll_eq_true Finset.univ _).mp hcheck c
    (Finset.mem_univ c)
  simp [checkCanonicalOwnerActive, howner] at hc
  exact hc

/-- The complete canonical input checker.  Its three components are limited
to operation freshness, source-local claim transfer, and membership of named
target owners in the builder's computed active set. -/
def checkCanonical
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) : Bool :=
  op.checkFresh A &&
  tr.checkTransfer A op.project &&
  checkCanonicalOwnerActive A tr op

/-- Logical output of `checkCanonical`; callers never supply this record. -/
structure CanonicalValid
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) : Prop where
  fresh : CanonicalOp.FreshValid A op
  transfer : Transfer.Valid A tr op.project
  owner_active : ∀ c b, tr.owner c = some b →
    b ∈ op.targetActive (contractSupport A.auth.allowed)

theorem checkCanonical_sound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (hcheck : checkCanonical A tr op = true) :
    CanonicalValid A tr op := by
  have hparts : (op.checkFresh A = true ∧
      tr.checkTransfer A op.project = true) ∧
      checkCanonicalOwnerActive A tr op = true := by
    simpa [checkCanonical] using hcheck
  exact {
    fresh := CanonicalOp.checkFresh_sound A op hparts.1.1
    transfer := Transfer.checkTransfer_sound A tr op.project hparts.1.2
    owner_active := checkCanonicalOwnerActive_sound A tr op hparts.2
  }

/-- Fully computed target of a canonical history transformation. -/
def canonicalTarget
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) :
    LifecycleState Coord Claim Branch Grant Operation where
  auth := tr.targetCore A (canonicalAllowed A op)
  grantOf := A.grantOf
  branchEpoch := op.targetEpoch A
  grantEpoch := A.grantEpoch
  tickets := A.tickets
  receipts := A.receipts

@[simp] theorem canonicalTarget_opClaim
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) (e : Operation) :
    (canonicalTarget A tr op).opClaim e = A.opClaim e := rfl

/-- Structural well-formedness of the computed target follows from the exact
preimage builder and checked transfer outputs. -/
theorem canonicalTarget_core_wf
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (hWF : LifecycleState.LWF A)
    (hActive : LifecycleState.ActiveExact A)
    (hValid : CanonicalValid A tr op) :
    WF (canonicalTarget A tr op).auth := by
  let target := canonicalTarget A tr op
  have hSupport := contractSupport_canonicalAllowed_eq A op hWF.core
    hActive hValid.fresh
  refine ⟨?_, ?_, ?_⟩
  · change ∅ ∈ canonicalAllowed A op
    rw [mem_canonicalAllowed_iff]
    refine ⟨Finset.empty_subset _, ?_, ?_⟩
    · simpa [canonicalProjection_zero] using hWF.core.empty_mem
    · intro _
      simp
  · intro C C' hC hsub
    change C ∈ canonicalAllowed A op at hC
    change C' ∈ canonicalAllowed A op
    rw [mem_canonicalAllowed_iff] at hC ⊢
    refine ⟨hsub.trans hC.1,
      hWF.core.downward hC.2.1 (canonicalProjection_mono op hsub), ?_⟩
    intro hexclusive
    have hinter : C' ∩ op.descendants ⊆ C ∩ op.descendants := by
      intro b hb
      exact Finset.mem_inter.mpr
        ⟨hsub (Finset.mem_inter.mp hb).1, (Finset.mem_inter.mp hb).2⟩
    exact (Finset.card_le_card hinter).trans (hC.2.2 hexclusive)
  · intro c b hstatus
    change tr.targetStatus A c = .tentative b at hstatus
    obtain ⟨source, hrho, howner⟩ :=
      (Transfer.targetStatus_tentative_iff A tr c b).1 hstatus
    have hbActive := hValid.owner_active c b howner
    have hbSupport : b ∈ contractSupport (canonicalAllowed A op) := by
      rw [hSupport]
      exact hbActive
    exact (mem_contractSupport_iff (canonicalAllowed A op) b).1 hbSupport

/-- The computed epoch map and exact preimage contract satisfy active-branch
exactness, not merely the one-way open-configuration property. -/
theorem canonicalTarget_active_exact
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (hWF : LifecycleState.LWF A)
    (hActive : LifecycleState.ActiveExact A)
    (hValid : CanonicalValid A tr op) :
    LifecycleState.ActiveExact (canonicalTarget A tr op) := by
  intro b
  change op.targetEpoch A b = .open ↔
    ∃ C ∈ canonicalAllowed A op, b ∈ C
  calc
    op.targetEpoch A b = .open ↔
        b ∈ op.targetActive (contractSupport A.auth.allowed) :=
      canonicalTargetEpoch_open_iff A op hActive hValid.fresh b
    _ ↔ b ∈ contractSupport (canonicalAllowed A op) := by
      rw [contractSupport_canonicalAllowed_eq A op hWF.core hActive
        hValid.fresh]
    _ ↔ ∃ C ∈ canonicalAllowed A op, b ∈ C :=
      mem_contractSupport_iff (canonicalAllowed A op) b

/-- Full lifecycle well-formedness of the computed target. -/
theorem canonicalTarget_lwf
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (hWF : LifecycleState.LWF A)
    (hActive : LifecycleState.ActiveExact A)
    (hValid : CanonicalValid A tr op) :
    LifecycleState.LWF (canonicalTarget A tr op) := by
  have hcore := canonicalTarget_core_wf A tr op hWF hActive hValid
  have htargetActive := canonicalTarget_active_exact A tr op hWF hActive hValid
  refine ⟨hcore, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · intro C hC b hbC
    exact (htargetActive b).2 ⟨C, hC, hbC⟩
  · intro c b hstatus
    exact (htargetActive b).2 (hcore.supported c b hstatus)
  · intro c b hstatus
    change tr.targetStatus A c = .tentative b at hstatus
    obtain ⟨source, hrho, howner⟩ :=
      (Transfer.targetStatus_tentative_iff A tr c b).1 hstatus
    obtain ⟨sourceOwner, hsource⟩ :=
      hValid.transfer.source_tentative c source hrho
    have hgrant := hValid.transfer.grant_agreement c source hrho
    change A.grantEpoch (A.grantOf c) = .open
    rw [hgrant]
    exact hWF.grant_open source sourceOwner hsource
  · exact hWF.ticket_receipt_disjoint
  · intro e c hop
    rw [canonicalTarget_opClaim] at hop
    change tr.targetStatus A c = .durable
    exact (Transfer.targetStatus_durable_iff A tr
      hValid.transfer.toCoreValid c).2 (hWF.bound_durable e c hop)
  · intro e e' c he he'
    rw [canonicalTarget_opClaim] at he he'
    exact hWF.binding_injective e e' c he he'

/-- Canonical simulation is derived from the exact contract preimage and the
load-bearing checked fiber theorem; no target AC check is performed. -/
theorem canonicalTarget_ac
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (hAC : AC A.auth)
    (hcheck : checkCanonical A tr op = true) :
    AC (canonicalTarget A tr op).auth := by
  have hparts : tr.checkTransfer A op.project = true := by
    have hall : (op.checkFresh A = true ∧
        tr.checkTransfer A op.project = true) ∧
        checkCanonicalOwnerActive A tr op = true := by
      simpa [checkCanonical] using hcheck
    exact hall.1.2
  have hvalid := (checkCanonical_sound A tr op hcheck).transfer.toCoreValid
  apply simulation_preserves_ac A.auth (canonicalTarget A tr op).auth
    op.project rfl hAC
  intro C hC
  change C ∈ canonicalAllowed A op at hC
  have hmem := (mem_canonicalAllowed_iff A op C).1 hC
  refine ⟨hmem.2.1, ?_⟩
  intro k
  change (tr.targetCore A (canonicalAllowed A op)).durableLoad k +
      (tr.targetCore A (canonicalAllowed A op)).conditionalLoad C k ≤
    A.auth.durableLoad k + A.auth.conditionalLoad (op.project C) k
  rw [Transfer.targetCore_durableLoad A tr hvalid
    (canonicalAllowed A op) k]
  exact Nat.add_le_add_left
    (Transfer.topology_fiber_conservation A tr op.project hparts
      (fun _ _ h => canonicalProjection_mono op h)
      (canonicalAllowed A op) C k) _

/-- Topology never revives a tombstoned claim ID. -/
theorem canonicalTarget_terminal_mono
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (hcheck : checkCanonical A tr op = true) :
    A.TerminalMonotone (canonicalTarget A tr op) := by
  have hvalid := (checkCanonical_sound A tr op hcheck).transfer.toCoreValid
  intro c hterminal
  change tr.targetStatus A c = .terminal
  exact Transfer.targetStatus_terminal_of_terminal A tr hvalid c hterminal

/-- Every canonical branch epoch update is monotone: fresh IDs open only from
`unissued`, a retired parent closes from `open`, and all other epochs are
unchanged.  Grant epochs are definitionally unchanged. -/
theorem canonicalTarget_epoch_mono
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (hcheck : checkCanonical A tr op = true) :
    A.EpochMonotone (canonicalTarget A tr op) := by
  have hvalid := checkCanonical_sound A tr op hcheck
  constructor
  · intro b
    change (A.branchEpoch b).Advances (op.targetEpoch A b)
    cases op with
    | choiceFork parent left right =>
        by_cases hfresh : b ∈ ({left, right} : Finset Branch)
        · have hs := hvalid.fresh.fresh_unissued b (by
            simpa [CanonicalOp.fresh] using hfresh)
          simp [CanonicalOp.targetEpoch, CanonicalOp.fresh, hfresh, hs,
            EpochStatus.Advances]
        · by_cases hparent : b = parent
          · subst b
            have hp : A.branchEpoch parent = .open := by
              simpa [CanonicalOp.parent] using hvalid.fresh.parent_open
            simp [CanonicalOp.targetEpoch, CanonicalOp.fresh,
              CanonicalOp.parent, CanonicalOp.retiresParent, hfresh, hp,
              EpochStatus.Advances]
          · simpa [CanonicalOp.targetEpoch, CanonicalOp.fresh,
              CanonicalOp.parent, hfresh, hparent] using
              EpochStatus.Advances.refl (A.branchEpoch b)
    | parallelFork parent left right =>
        by_cases hfresh : b ∈ ({left, right} : Finset Branch)
        · have hs := hvalid.fresh.fresh_unissued b (by
            simpa [CanonicalOp.fresh] using hfresh)
          simp [CanonicalOp.targetEpoch, CanonicalOp.fresh, hfresh, hs,
            EpochStatus.Advances]
        · by_cases hparent : b = parent
          · subst b
            have hp : A.branchEpoch parent = .open := by
              simpa [CanonicalOp.parent] using hvalid.fresh.parent_open
            simp [CanonicalOp.targetEpoch, CanonicalOp.fresh,
              CanonicalOp.parent, CanonicalOp.retiresParent, hfresh, hp,
              EpochStatus.Advances]
          · simpa [CanonicalOp.targetEpoch, CanonicalOp.fresh,
              CanonicalOp.parent, hfresh, hparent] using
              EpochStatus.Advances.refl (A.branchEpoch b)
    | replaceRestore parent restored =>
        by_cases hfresh : b = restored
        · subst b
          have hs := hvalid.fresh.fresh_unissued restored (by
            simp [CanonicalOp.fresh])
          simp [CanonicalOp.targetEpoch, CanonicalOp.fresh, hs,
            EpochStatus.Advances]
        · by_cases hparent : b = parent
          · subst b
            have hp : A.branchEpoch parent = .open := by
              simpa [CanonicalOp.parent] using hvalid.fresh.parent_open
            simp [CanonicalOp.targetEpoch, CanonicalOp.fresh,
              CanonicalOp.parent, CanonicalOp.retiresParent, hfresh, hp,
              EpochStatus.Advances]
          · simpa [CanonicalOp.targetEpoch, CanonicalOp.fresh,
              CanonicalOp.parent, hfresh, hparent] using
              EpochStatus.Advances.refl (A.branchEpoch b)
    | liveRestore parent restored =>
        by_cases hfresh : b = restored
        · subst b
          have hs := hvalid.fresh.fresh_unissued restored (by
            simp [CanonicalOp.fresh])
          simp [CanonicalOp.targetEpoch, CanonicalOp.fresh, hs,
            EpochStatus.Advances]
        · simpa [CanonicalOp.targetEpoch, CanonicalOp.fresh,
            CanonicalOp.retiresParent, hfresh] using
            EpochStatus.Advances.refl (A.branchEpoch b)
  · intro g
    exact EpochStatus.Advances.refl _

/-- Stable protected-operation bindings survive every canonical topology
change byte-for-byte. -/
theorem canonicalTarget_existing_binding
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) :
    ∀ e, (canonicalTarget A tr op).opClaim e = A.opClaim e :=
  canonicalTarget_opClaim A tr op

/-- Shared preservation theorem used by all four operation-specific wrappers. -/
theorem canonical_preserves_wf_ac
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (hWF : LifecycleState.LWF A) (hAC : AC A.auth)
    (hActive : LifecycleState.ActiveExact A)
    (hcheck : checkCanonical A tr op = true) :
    LifecycleState.LWF (canonicalTarget A tr op) ∧
      AC (canonicalTarget A tr op).auth ∧
      LifecycleState.ActiveExact (canonicalTarget A tr op) := by
  have hvalid := checkCanonical_sound A tr op hcheck
  exact ⟨canonicalTarget_lwf A tr op hWF hActive hvalid,
    canonicalTarget_ac A tr op hAC hcheck,
    canonicalTarget_active_exact A tr op hWF hActive hvalid⟩

theorem choiceFork_preserves_wf_ac
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (parent left right : Branch)
    (hWF : LifecycleState.LWF A) (hAC : AC A.auth)
    (hActive : LifecycleState.ActiveExact A)
    (hcheck : checkCanonical A tr (.choiceFork parent left right) = true) :
    LifecycleState.LWF
        (canonicalTarget A tr (.choiceFork parent left right)) ∧
      AC (canonicalTarget A tr (.choiceFork parent left right)).auth ∧
      LifecycleState.ActiveExact
        (canonicalTarget A tr (.choiceFork parent left right)) :=
  canonical_preserves_wf_ac A tr _ hWF hAC hActive hcheck

theorem parallelFork_preserves_wf_ac
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (parent left right : Branch)
    (hWF : LifecycleState.LWF A) (hAC : AC A.auth)
    (hActive : LifecycleState.ActiveExact A)
    (hcheck : checkCanonical A tr (.parallelFork parent left right) = true) :
    LifecycleState.LWF
        (canonicalTarget A tr (.parallelFork parent left right)) ∧
      AC (canonicalTarget A tr (.parallelFork parent left right)).auth ∧
      LifecycleState.ActiveExact
        (canonicalTarget A tr (.parallelFork parent left right)) :=
  canonical_preserves_wf_ac A tr _ hWF hAC hActive hcheck

theorem replaceRestore_preserves_wf_ac
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (parent restored : Branch)
    (hWF : LifecycleState.LWF A) (hAC : AC A.auth)
    (hActive : LifecycleState.ActiveExact A)
    (hcheck : checkCanonical A tr (.replaceRestore parent restored) = true) :
    LifecycleState.LWF
        (canonicalTarget A tr (.replaceRestore parent restored)) ∧
      AC (canonicalTarget A tr (.replaceRestore parent restored)).auth ∧
      LifecycleState.ActiveExact
        (canonicalTarget A tr (.replaceRestore parent restored)) :=
  canonical_preserves_wf_ac A tr _ hWF hAC hActive hcheck

theorem liveRestore_preserves_wf_ac
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (parent restored : Branch)
    (hWF : LifecycleState.LWF A) (hAC : AC A.auth)
    (hActive : LifecycleState.ActiveExact A)
    (hcheck : checkCanonical A tr (.liveRestore parent restored) = true) :
    LifecycleState.LWF
        (canonicalTarget A tr (.liveRestore parent restored)) ∧
      AC (canonicalTarget A tr (.liveRestore parent restored)).auth ∧
      LifecycleState.ActiveExact
        (canonicalTarget A tr (.liveRestore parent restored)) :=
  canonical_preserves_wf_ac A tr _ hWF hAC hActive hcheck

end AuthorityContinuity
