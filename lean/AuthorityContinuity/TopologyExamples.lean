import AuthorityContinuity.Topology
import AuthorityContinuity.Merge

/-!
# Executable separating examples for canonical topology and Merge

These finite witnesses are deliberately small.  They exercise the checked
interfaces used by the preservation theorems rather than merely evaluating
`AC` on hand-written targets.  The positive preflight splits one source claim
into two preallocated fresh IDs and sends it through the canonical parallel
Fork builder, transfer checker, fiber-conservation proof, and preservation
theorem.
-/

namespace AuthorityContinuity.TopologyExamples

abbrev Coord := Fin 1
abbrev Claim := Fin 3
abbrev Branch := Fin 3
abbrev Grant := Fin 1
abbrev Operation := Fin 1

namespace Claim
def source : Claim := 0
def leftFragment : Claim := 1
def rightFragment : Claim := 2
end Claim

namespace Branch
def parent : Branch := 0
def left : Branch := 1
def right : Branch := 2
end Branch

open Claim Branch

/-- One two-unit conditional claim on the only active source branch. -/
def source : LifecycleState Coord Claim Branch Grant Operation where
  auth := {
    capacity := fun _ => 2
    demand := fun c _ => if c = Claim.source then 2 else 1
    status := fun c => if c = Claim.source then .tentative .parent else .unissued
    allowed := ({Branch.parent} : Finset Branch).powerset
  }
  grantOf := fun _ => 0
  branchEpoch := fun b => if b = Branch.parent then .open else .unissued
  grantEpoch := fun _ => .open
  tickets := fun _ => none
  receipts := fun _ => none

/-- Replace the source claim by two one-unit fresh fragments. -/
def splitTransfer : Transfer Claim Branch where
  owner := fun c =>
    if c = Claim.leftFragment then some Branch.left
    else if c = Claim.rightFragment then some Branch.right
    else none
  rho := fun c =>
    if c = Claim.leftFragment ∨ c = Claim.rightFragment then some Claim.source
    else none

/-- A one-fragment transfer used by replacing restore. -/
def replaceTransfer : Transfer Claim Branch where
  owner := fun c => if c = Claim.leftFragment then some Branch.right else none
  rho := fun c => if c = Claim.leftFragment then some Claim.source else none

/-- Live restore conservatively splits authority between old and new lives. -/
def liveTransfer : Transfer Claim Branch where
  owner := fun c =>
    if c = Claim.leftFragment then some Branch.parent
    else if c = Claim.rightFragment then some Branch.right
    else none
  rho := fun c =>
    if c = Claim.leftFragment ∨ c = Claim.rightFragment then some Claim.source
    else none

theorem source_lwf : source.LWF := by
  refine ⟨⟨?_, ?_, ?_⟩, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · simp [source]
  · intro C C' hC hsub
    exact Finset.mem_powerset.mpr
      (hsub.trans (Finset.mem_powerset.mp hC))
  · intro c b hstatus
    by_cases hc : c = Claim.source
    · have hb : b = Branch.parent := by
        simpa [source, hc] using hstatus.symm
      subst b
      exact ⟨{Branch.parent}, by simp [source], by simp⟩
    · simp [source, hc] at hstatus
  · intro C hC b hbC
    have hb : b = Branch.parent :=
      Finset.mem_singleton.mp ((Finset.mem_powerset.mp hC) hbC)
    simp [source, hb]
  · intro c b hstatus
    by_cases hc : c = Claim.source
    · have hb : b = Branch.parent := by
        simpa [source, hc] using hstatus.symm
      simp [source, hb]
    · simp [source, hc] at hstatus
  · intro c b hstatus
    simp [LifecycleState.claimOpen, source]
  · intro e t r ht
    simp [source] at ht
  · intro e c hop
    simp [LifecycleState.opClaim, source] at hop
  · intro e e' c hop
    simp [LifecycleState.opClaim, source] at hop

theorem source_ac : AC source.auth :=
  checkAC_sound source.auth (by decide)

theorem source_active_exact : source.ActiveExact := by
  intro b
  constructor
  · intro hopen
    have hb : b = Branch.parent := by
      simpa [source] using hopen
    subst b
    exact ⟨{Branch.parent}, by simp [source], by simp⟩
  · rintro ⟨C, hC, hbC⟩
    have hb : b = Branch.parent :=
      Finset.mem_singleton.mp ((Finset.mem_powerset.mp hC) hbC)
    simp [source, hb]

theorem choice_fork_admission_accepts : checkCanonical source splitTransfer
    (.choiceFork .parent .left .right) = true := by native_decide

theorem parallel_fork_admission_accepts : checkCanonical source splitTransfer
    (.parallelFork .parent .left .right) = true := by native_decide

theorem replace_restore_admission_accepts : checkCanonical source replaceTransfer
    (.replaceRestore .parent .right) = true := by native_decide

theorem live_restore_admission_accepts : checkCanonical source liveTransfer
    (.liveRestore .parent .right) = true := by native_decide

/-- Real preflight: fresh fragmentation reaches the final parallel-Fork
preservation theorem; `canonicalTarget_ac` invokes fiber conservation. -/
theorem fresh_fragment_parallel_preflight :
    (canonicalTarget source splitTransfer
      (.parallelFork .parent .left .right)).LWF ∧
    AC (canonicalTarget source splitTransfer
      (.parallelFork .parent .left .right)).auth ∧
    (canonicalTarget source splitTransfer
      (.parallelFork .parent .left .right)).ActiveExact := by
  exact parallelFork_preserves_wf_ac source splitTransfer
    .parent .left .right source_lwf source_ac source_active_exact (by decide)

/-- Choice has both children as alternatives but never jointly. -/
theorem choice_rejects_child_copresence : ({.left, .right} : Finset Branch) ∉
    canonicalAllowed source (.choiceFork .parent .left .right) := by
  native_decide

/-- Parallel Fork admits their joint continuation after conservative split. -/
theorem parallel_accepts_child_copresence : ({.left, .right} : Finset Branch) ∈
    canonicalAllowed source (.parallelFork .parent .left .right) := by
  native_decide

/-- Copying the full source demand into both co-durable children is rejected. -/
def copiedDemandSource : LifecycleState Coord Claim Branch Grant Operation :=
  { source with auth := {
      source.auth with
      demand := fun _ _ => 2
    }
  }

theorem copied_full_demand_rejected : checkCanonical copiedDemandSource splitTransfer
    (.parallelFork .parent .left .right) = false := by native_decide

/-- A retained ID cannot coexist with a second fresh member of its fiber. -/
def retainedPlusFragment : Transfer Claim Branch where
  owner := fun c =>
    if c = Claim.source then some Branch.left
    else if c = Claim.leftFragment then some Branch.right
    else none
  rho := fun c =>
    if c = Claim.source ∨ c = Claim.leftFragment then some Claim.source else none

theorem retained_fragment_mix_rejected :
    retainedPlusFragment.checkTransferCore source = false := by
  native_decide

/-- Terminal IDs are not a fragment pool. -/
def terminalFragmentSource : LifecycleState Coord Claim Branch Grant Operation :=
  { source with auth := {
      source.auth with
      status := fun c =>
        if c = Claim.source then .tentative .parent
        else if c = Claim.leftFragment then .terminal
        else .unissued
    }
  }

theorem terminal_fragment_reuse_rejected :
    splitTransfer.checkTransferCore terminalFragmentSource = false := by
  native_decide

/-- `rho` may target only a source tentative claim. -/
def nonTentativeRho : Transfer Claim Branch where
  owner := fun c => if c = Claim.leftFragment then some Branch.left else none
  rho := fun c =>
    if c = Claim.leftFragment then some Claim.rightFragment else none

theorem nontentative_rho_rejected :
    nonTentativeRho.checkTransferCore source = false := by
  native_decide

/-- A closed epoch cannot be reused as a fresh branch identity. -/
def closedChildSource : LifecycleState Coord Claim Branch Grant Operation :=
  { source with branchEpoch := fun b =>
      if b = Branch.parent then .open
      else if b = Branch.left then .closed
      else .unissued
  }

theorem closed_epoch_reopen_rejected : checkCanonical closedChildSource splitTransfer
    (.parallelFork .parent .left .right) = false := by native_decide

/-- Identity Merge preserves the checked source and works in both modes. -/
def identityTransfer : Transfer Claim Branch where
  owner := fun c => if c = Claim.source then some Branch.parent else none
  rho := fun c => if c = Claim.source then some Claim.source else none

def identityMerge : MergeDescriptor Claim Branch where
  allowed := source.auth.allowed
  branchEpoch := source.branchEpoch
  transfer := identityTransfer

theorem simulation_merge_identity_accepts :
    MergeCheck.simulationAdmission source identityMerge id = true := by
  native_decide

theorem direct_merge_identity_accepts :
    MergeCheck.directAdmission source identityMerge = true := by
  native_decide

/-- Direct admission and simulation admission are observably different: the
target is safe, but this proposed projection erases its loaded configuration. -/
def eraseProjection (_ : Finset Branch) : Finset Branch := ∅

theorem merge_modes_separated :
    MergeCheck.directAdmission source identityMerge = true ∧
    MergeCheck.simulationAdmission source identityMerge eraseProjection = false := by
  native_decide

/-- Two individually safe alternatives become unsafe if Merge makes them
co-durable without acquiring capacity.  Structure and transfer still pass;
direct target admission is the rejecting check. -/
def exclusiveSource : LifecycleState Coord Claim Branch Grant Operation where
  auth := {
    capacity := fun _ => 2
    demand := fun c _ => if c = Claim.rightFragment then 0 else 2
    status := fun c =>
      if c = Claim.source then .tentative .left
      else if c = Claim.leftFragment then .tentative .right
      else .unissued
    allowed := {∅, {.left}, {.right}}
  }
  grantOf := fun _ => 0
  branchEpoch := fun b => if b = Branch.parent then .unissued else .open
  grantEpoch := fun _ => .open
  tickets := fun _ => none
  receipts := fun _ => none

def retainAlternatives : Transfer Claim Branch where
  owner := fun c =>
    if c = Claim.source then some Branch.left
    else if c = Claim.leftFragment then some Branch.right
    else none
  rho := fun c =>
    if c = Claim.source then some Claim.source
    else if c = Claim.leftFragment then some Claim.leftFragment
    else none

def unsafeCoDurableMerge : MergeDescriptor Claim Branch where
  allowed := {∅, {.left}, {.right}, {.left, .right}}
  branchEpoch := exclusiveSource.branchEpoch
  transfer := retainAlternatives

theorem exclusive_source_ac : checkAC exclusiveSource.auth = true := by
  native_decide

theorem unsafe_codurable_direct_merge_rejected :
    MergeCheck.structural exclusiveSource unsafeCoDurableMerge = true ∧
    checkAC (unsafeCoDurableMerge.target exclusiveSource).auth = false ∧
    MergeCheck.directAdmission exclusiveSource unsafeCoDurableMerge = false := by
  native_decide

/-- Canonical topology cannot mutate durable control history. -/
theorem canonical_history_definitionally_preserved :
    (canonicalTarget source splitTransfer
      (.parallelFork .parent .left .right)).tickets = source.tickets ∧
    (canonicalTarget source splitTransfer
      (.parallelFork .parent .left .right)).receipts = source.receipts ∧
    (canonicalTarget source splitTransfer
      (.parallelFork .parent .left .right)).grantEpoch = source.grantEpoch := by
  exact ⟨rfl, rfl, rfl⟩

/-- Replacing restore closes the old branch rather than keeping two lives. -/
theorem replace_restore_closes_parent :
    (canonicalTarget source replaceTransfer
      (.replaceRestore .parent .right)).branchEpoch .parent = EpochStatus.closed := by
  rfl

#print axioms fresh_fragment_parallel_preflight

end AuthorityContinuity.TopologyExamples
