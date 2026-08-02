import AuthorityContinuity.Topology

/-!
# Root transport for every tentative claim

This module supplies the non-batch bridge between the checked transfer
semantics and a residual plan envelope.  The target lineage is computed only
from the source lineage and the transfer's actual `rho`; no caller supplies a
target root map.  The load theorem ranges over every tentative target claim,
including claims outside any selected promotion batch.
-/

namespace AuthorityContinuity.PlanRootTransport

open AuthorityContinuity

universe uC uI uB uG uO uS

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO} {Slot : Type uS}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [DecidableEq Claim]
variable [Fintype Branch] [DecidableEq Branch]
variable [DecidableEq Grant] [DecidableEq Slot]

/-! ## Computed lineage and all-tentative load -/

/-- The only admitted target root map: follow the actual refinement edge and
then read the immutable root of its source. -/
def transportedRoot (root : Claim -> Option Slot)
    (tr : Transfer Claim Branch) (c' : Claim) : Option Slot :=
  (tr.rho c').bind root

@[simp] theorem transportedRoot_of_rho
    (root : Claim -> Option Slot) (tr : Transfer Claim Branch)
    {c c' : Claim} (hrho : tr.rho c' = some c) :
    transportedRoot root tr c' = root c := by
  simp [transportedRoot, hrho]

/-- Every tentative claim at one lineage label.  The label is an `Option`, so
the theorem below covers scheduled roots and the explicit `none` class. -/
def tentativeLineageClaims
    (A : State Coord Claim Branch) (root : Claim -> Option Slot)
    (r : Option Slot) : Finset Claim :=
  Finset.univ.filter fun c =>
    (exists b, A.status c = .tentative b) /\ root c = r

/-- `L`: demand of all tentative claims at a lineage label, not merely the
selected promotion batch. -/
def tentativeLineageLoad
    (A : State Coord Claim Branch) (root : Claim -> Option Slot)
    (r : Option Slot) (k : Coord) : Nat :=
  ∑ c ∈ tentativeLineageClaims A root r, A.demand c k

/-- Scheduled-root specialization used by an `L_i + E_i <= R_i` envelope. -/
def tentativeRootLoad
    (A : State Coord Claim Branch) (root : Claim -> Option Slot)
    (s : Slot) (k : Coord) : Nat :=
  tentativeLineageLoad A root (some s) k

/-- Every tentative claim in the actual computed target has a real tentative
source and inherits exactly that source's root. -/
theorem targetCore_tentative_root_inherited
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (allowed : Finset (Finset Branch))
    (root : Claim -> Option Slot) (valid : Transfer.CoreValid A tr)
    {c' : Claim} {b' : Branch}
    (htarget : (tr.targetCore A allowed).status c' = .tentative b') :
    exists c b,
      tr.rho c' = some c /\
      A.auth.status c = .tentative b /\
      transportedRoot root tr c' = root c := by
  change tr.targetStatus A c' = .tentative b' at htarget
  obtain ⟨c, hrho, _⟩ :=
    (Transfer.targetStatus_tentative_iff A tr c' b').1 htarget
  obtain ⟨b, hsource⟩ := valid.source_tentative c' c hrho
  exact ⟨c, b, hrho, hsource, transportedRoot_of_rho root tr hrho⟩

/-- Fiber conservation lifts from each checked `rho` fiber to every complete
tentative lineage class.  In particular, it accounts for non-batch claims and
for the `none` lineage instead of silently dropping either. -/
theorem targetCore_tentative_lineage_load_le
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (allowed : Finset (Finset Branch))
    (root : Claim -> Option Slot) (valid : Transfer.CoreValid A tr)
    (r : Option Slot) (k : Coord) :
    tentativeLineageLoad (tr.targetCore A allowed)
        (transportedRoot root tr) r k <=
      tentativeLineageLoad A.auth root r k := by
  classical
  let targetClaims := tentativeLineageClaims (tr.targetCore A allowed)
    (transportedRoot root tr) r
  let sourceClaims := tentativeLineageClaims A.auth root r
  let sourceOptions : Finset (Option Claim) := sourceClaims.image some
  have hsubset : targetClaims ⊆
      Finset.univ.filter fun c' => tr.rho c' ∈ sourceOptions := by
    intro c' hc'
    have htarget : c' ∈ tentativeLineageClaims (tr.targetCore A allowed)
        (transportedRoot root tr) r := hc'
    simp only [tentativeLineageClaims, Finset.mem_filter, Finset.mem_univ,
      true_and] at htarget
    obtain ⟨⟨b', hstatus⟩, hroot⟩ := htarget
    obtain ⟨c, b, hrho, hsource, hinherit⟩ :=
      targetCore_tentative_root_inherited A tr allowed root valid hstatus
    have hcSource : c ∈ sourceClaims := by
      simp only [sourceClaims, tentativeLineageClaims, Finset.mem_filter,
        Finset.mem_univ, true_and]
      exact ⟨⟨b, hsource⟩, hinherit.symm.trans hroot⟩
    simp only [Finset.mem_filter, Finset.mem_univ, true_and]
    exact Finset.mem_image.mpr ⟨c, hcSource, hrho.symm⟩
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
        ∑ c ∈ sourceClaims,
          ∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = some c,
            A.auth.demand c' k := by
    dsimp [sourceOptions]
    rw [Finset.sum_image]
    exact Option.some_injective Claim |>.injOn
  unfold tentativeLineageLoad
  change (∑ c' ∈ targetClaims, A.auth.demand c' k) <=
    ∑ c ∈ sourceClaims, A.auth.demand c k
  calc
    (∑ c' ∈ targetClaims, A.auth.demand c' k) <=
        ∑ c' ∈ Finset.univ.filter
          (fun c' => tr.rho c' ∈ sourceOptions), A.auth.demand c' k :=
      Finset.sum_le_sum_of_subset hsubset
    _ = ∑ source ∈ sourceOptions,
          ∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = source,
            A.auth.demand c' k := hfiberwise
    _ = ∑ c ∈ sourceClaims,
          ∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = some c,
            A.auth.demand c' k := hreindex
    _ <= ∑ c ∈ sourceClaims, A.auth.demand c k :=
      Finset.sum_le_sum fun c _ => valid.fiber_demand c k

/-- The residual-envelope form: all target tentative demand charged to root
`s` is no greater than the corresponding source `L_s`. -/
theorem targetCore_tentative_root_load_le
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (allowed : Finset (Finset Branch))
    (root : Claim -> Option Slot) (valid : Transfer.CoreValid A tr)
    (s : Slot) (k : Coord) :
    tentativeRootLoad (tr.targetCore A allowed)
        (transportedRoot root tr) s k <=
      tentativeRootLoad A.auth root s k :=
  targetCore_tentative_lineage_load_le A tr allowed root valid (some s) k

/-! ## Corollaries for the actual canonical target -/

theorem canonicalTarget_tentative_root_inherited
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (root : Claim -> Option Slot) (valid : CanonicalValid A tr op)
    {c' : Claim} {b' : Branch}
    (htarget : (canonicalTarget A tr op).auth.status c' = .tentative b') :
    exists c b,
      tr.rho c' = some c /\
      A.auth.status c = .tentative b /\
      transportedRoot root tr c' = root c :=
  targetCore_tentative_root_inherited A tr (canonicalAllowed A op) root
    valid.transfer.toCoreValid htarget

theorem canonicalTarget_tentative_lineage_load_le
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (root : Claim -> Option Slot) (valid : CanonicalValid A tr op)
    (r : Option Slot) (k : Coord) :
    tentativeLineageLoad (canonicalTarget A tr op).auth
        (transportedRoot root tr) r k <=
      tentativeLineageLoad A.auth root r k :=
  targetCore_tentative_lineage_load_le A tr (canonicalAllowed A op) root
    valid.transfer.toCoreValid r k

theorem canonicalTarget_tentative_root_load_le
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (root : Claim -> Option Slot) (valid : CanonicalValid A tr op)
    (s : Slot) (k : Coord) :
    tentativeRootLoad (canonicalTarget A tr op).auth
        (transportedRoot root tr) s k <=
      tentativeRootLoad A.auth root s k :=
  targetCore_tentative_root_load_le A tr (canonicalAllowed A op) root
    valid.transfer.toCoreValid s k

/-! ## Executable owner/root purity -/

/-- An owner cannot combine claims descended from different lineage labels.
Equality is over `Option Slot`, so `some`/`none` mixing is rejected too. -/
def OwnerRootPure (A : State Coord Claim Branch)
    (root : Claim -> Option Slot) : Prop :=
  forall c c' b,
    A.status c = .tentative b ->
    A.status c' = .tentative b ->
    root c = root c'

def checkOwnerRootPure (A : State Coord Claim Branch)
    (root : Claim -> Option Slot) : Bool :=
  finiteAll Finset.univ fun c : Claim =>
    finiteAll Finset.univ fun c' : Claim =>
      match A.status c, A.status c' with
      | .tentative b, .tentative b' =>
          if b = b' then decide (root c = root c') else true
      | _, _ => true

theorem checkOwnerRootPure_sound
    {A : State Coord Claim Branch} {root : Claim -> Option Slot}
    (hcheck : checkOwnerRootPure A root = true) :
    OwnerRootPure A root := by
  intro c c' b hc hc'
  have hrow := (finiteAll_eq_true Finset.univ _).mp hcheck c
    (Finset.mem_univ c)
  have hpair := (finiteAll_eq_true Finset.univ _).mp hrow c'
    (Finset.mem_univ c')
  simpa [checkOwnerRootPure, hc, hc'] using hpair

theorem checkOwnerRootPure_rejects_mixed
    {A : State Coord Claim Branch} {root : Claim -> Option Slot}
    {c c' : Claim} {b : Branch}
    (hc : A.status c = .tentative b)
    (hc' : A.status c' = .tentative b)
    (hmixed : root c ≠ root c') :
    checkOwnerRootPure A root = false := by
  apply Bool.eq_false_of_not_eq_true
  intro htrue
  exact hmixed (checkOwnerRootPure_sound htrue c c' b hc hc')

theorem checkOwnerRootPure_rejects_distinct_roots
    {A : State Coord Claim Branch} {root : Claim -> Option Slot}
    {c c' : Claim} {b : Branch} {s t : Slot}
    (hc : A.status c = .tentative b)
    (hc' : A.status c' = .tentative b)
    (hroot : root c = some s) (hroot' : root c' = some t)
    (hst : s ≠ t) :
    checkOwnerRootPure A root = false := by
  apply checkOwnerRootPure_rejects_mixed hc hc'
  intro heq
  rw [hroot, hroot'] at heq
  exact hst (Option.some.inj heq)

theorem checkOwnerRootPure_rejects_some_none
    {A : State Coord Claim Branch} {root : Claim -> Option Slot}
    {c c' : Claim} {b : Branch} {s : Slot}
    (hc : A.status c = .tentative b)
    (hc' : A.status c' = .tentative b)
    (hroot : root c = some s) (hroot' : root c' = none) :
    checkOwnerRootPure A root = false := by
  apply checkOwnerRootPure_rejects_mixed hc hc'
  rw [hroot, hroot']
  exact Option.some_ne_none s

/-- The executable check instantiated on the actual computed target and its
only admissible transported root map. -/
def checkTargetOwnerRootPure
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (allowed : Finset (Finset Branch))
    (root : Claim -> Option Slot) : Bool :=
  checkOwnerRootPure (tr.targetCore A allowed) (transportedRoot root tr)

theorem checkTargetOwnerRootPure_sound
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {tr : Transfer Claim Branch} {allowed : Finset (Finset Branch)}
    {root : Claim -> Option Slot}
    (hcheck : checkTargetOwnerRootPure A tr allowed root = true) :
    OwnerRootPure (tr.targetCore A allowed) (transportedRoot root tr) :=
  checkOwnerRootPure_sound hcheck

/-- The target checker concretely rejects an owner that combines two
scheduled, distinct inherited roots. -/
theorem checkTargetOwnerRootPure_rejects_distinct_roots
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {tr : Transfer Claim Branch} {allowed : Finset (Finset Branch)}
    {root : Claim -> Option Slot} {c c' : Claim} {b : Branch} {s t : Slot}
    (hc : (tr.targetCore A allowed).status c = .tentative b)
    (hc' : (tr.targetCore A allowed).status c' = .tentative b)
    (hroot : transportedRoot root tr c = some s)
    (hroot' : transportedRoot root tr c' = some t)
    (hst : s ≠ t) :
    checkTargetOwnerRootPure A tr allowed root = false :=
  checkOwnerRootPure_rejects_distinct_roots hc hc' hroot hroot' hst

/-- The same checker rejects mixing a scheduled root with an explicit
unassigned (`none`) lineage under one target owner. -/
theorem checkTargetOwnerRootPure_rejects_some_none
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {tr : Transfer Claim Branch} {allowed : Finset (Finset Branch)}
    {root : Claim -> Option Slot} {c c' : Claim} {b : Branch} {s : Slot}
    (hc : (tr.targetCore A allowed).status c = .tentative b)
    (hc' : (tr.targetCore A allowed).status c' = .tentative b)
    (hroot : transportedRoot root tr c = some s)
    (hroot' : transportedRoot root tr c' = none) :
    checkTargetOwnerRootPure A tr allowed root = false :=
  checkOwnerRootPure_rejects_some_none hc hc' hroot hroot'

#print axioms targetCore_tentative_root_inherited
#print axioms targetCore_tentative_lineage_load_le
#print axioms canonicalTarget_tentative_root_load_le
#print axioms checkOwnerRootPure_sound
#print axioms checkTargetOwnerRootPure_rejects_distinct_roots
#print axioms checkTargetOwnerRootPure_rejects_some_none

end AuthorityContinuity.PlanRootTransport
