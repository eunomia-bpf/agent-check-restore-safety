import AuthorityContinuity.Lifecycle

/-!
# Checked claim transfer for history-transforming topology steps

This module isolates the finite claim-transfer part of Fork, Restore, and
Merge.  A transfer names the target owner of every surviving tentative claim
and maps that target ID back to its unique source claim.  The target status is
computed: old tentative IDs outside the image become terminal, while durable,
terminal, and unissued history is otherwise unchanged.

The Boolean checker is deliberately atomized.  Its core checks exact domains,
source provenance, fresh-versus-retained fibers, grant agreement, and
coordinatewise demand conservation.  The projection-aware checker adds only
the local owner/projection atom.  It never checks target `WF`, `AC`, or a
per-configuration load simulation.
-/

namespace AuthorityContinuity

universe uC uI uB uG uO

/-- Finite transfer data for tentative claims.  `rho c' = some c` says that
target ID `c'` refines source claim `c`; `owner c'` is its target owner. -/
structure Transfer (Claim : Type uI) (Branch : Type uB) where
  owner : Claim → Option Branch
  rho : Claim → Option Claim

namespace Transfer

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [DecidableEq Claim]
variable [Fintype Branch] [DecidableEq Branch]
variable [DecidableEq Grant]

/-- Computed target claim status.  A malformed one-sided transfer entry is
not made tentative; `checkTransferCore` rejects it. -/
def targetStatus
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (c : Claim) : ClaimStatus Branch :=
  match tr.rho c, tr.owner c with
  | some _, some b => .tentative b
  | _, _ =>
      match A.auth.status c with
      | .tentative _ => .terminal
      | s => s

/-- Claim-level target core.  The topology builder supplies the exact target
configuration family; transfer supplies only the computed claim ledger. -/
def targetCore
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (allowed : Finset (Finset Branch)) :
    State Coord Claim Branch where
  capacity := A.auth.capacity
  demand := A.auth.demand
  status := tr.targetStatus A
  allowed := allowed

/-- The owner and refinement maps have exactly the same finite domain. -/
def checkExactDomain (tr : Transfer Claim Branch) : Bool :=
  finiteAll Finset.univ fun c =>
    decide ((tr.owner c).isSome = (tr.rho c).isSome)

/-- Every refinement target is tentative in the source. -/
def checkSourceTentative
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) : Bool :=
  finiteAll Finset.univ fun c' =>
    match tr.rho c' with
    | none => true
    | some c =>
        match A.auth.status c with
        | .tentative _ => true
        | _ => false

/-- A target ID is either its retained source ID or was unissued before the
step.  Terminal IDs are therefore never a fragment pool. -/
def checkProvenance
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) : Bool :=
  finiteAll Finset.univ fun c' =>
    match tr.rho c' with
    | none => true
    | some c => decide (c' = c ∨ A.auth.status c' = .unissued)

/-- A retained source ID excludes every distinct fresh member from its fiber.
Together with provenance, each fiber is retained-only or all-fresh. -/
def checkNoMixedFiber (tr : Transfer Claim Branch) : Bool :=
  finiteAll Finset.univ fun c =>
    if tr.rho c = some c then
      finiteAll Finset.univ fun c' =>
        decide (tr.rho c' = some c → c' = c)
    else true

/-- Preallocated fragment IDs carry the same immutable grant metadata as
their source claim. -/
def checkGrantAgreement
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) : Bool :=
  finiteAll Finset.univ fun c' =>
    match tr.rho c' with
    | none => true
    | some c => decide (A.grantOf c' = A.grantOf c)

/-- Every coordinate of every source fiber is demand-conservative. -/
def checkFiberDemand
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) : Bool :=
  finiteAll Finset.univ fun c =>
    finiteAll Finset.univ fun k =>
      decide
        ((∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = some c,
            A.auth.demand c' k) ≤ A.auth.demand c k)

/-- Projection-free transfer admission, shared by direct Merge. -/
def checkTransferCore
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) : Bool :=
  checkExactDomain tr &&
  checkSourceTentative A tr &&
  checkProvenance A tr &&
  checkNoMixedFiber tr &&
  checkGrantAgreement A tr &&
  checkFiberDemand A tr

/-- Local checked relation between a target owner and its source owner.  A
canonical monotone projection later lifts this singleton fact to arbitrary
target configurations. -/
def checkOwnerProjection
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (project : Finset Branch → Finset Branch) : Bool :=
  finiteAll Finset.univ fun c' =>
    match tr.rho c', tr.owner c' with
    | none, none => true
    | some c, some b' =>
        match A.auth.status c with
        | .tentative b => decide (b ∈ project {b'})
        | _ => false
    | _, _ => false

/-- Projection-aware transfer admission for canonical and simulation steps. -/
def checkTransfer
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (project : Finset Branch → Finset Branch) : Bool :=
  checkTransferCore A tr && checkOwnerProjection A tr project

/-- Logical facts emitted by the projection-free checker.  Callers receive
this record only from `checkTransferCore_sound`; it is not an input
certificate. -/
structure CoreValid
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) : Prop where
  exact_domain : ∀ c, (tr.owner c).isSome = (tr.rho c).isSome
  source_tentative : ∀ c' c, tr.rho c' = some c →
    ∃ b, A.auth.status c = .tentative b
  provenance : ∀ c' c, tr.rho c' = some c →
    c' = c ∨ A.auth.status c' = .unissued
  retained_fiber_exact : ∀ c, tr.rho c = some c →
    ∀ c', tr.rho c' = some c → c' = c
  grant_agreement : ∀ c' c, tr.rho c' = some c →
    A.grantOf c' = A.grantOf c
  fiber_demand : ∀ c k,
    (∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = some c,
      A.auth.demand c' k) ≤ A.auth.demand c k

/-- Full facts emitted by the projection-aware transfer checker. -/
structure Valid
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (project : Finset Branch → Finset Branch) : Prop
    extends CoreValid A tr where
  owner_projection : ∀ c' c b' b,
    tr.rho c' = some c → tr.owner c' = some b' →
    A.auth.status c = .tentative b → b ∈ project {b'}

theorem checkExactDomain_sound (tr : Transfer Claim Branch)
    (hcheck : checkExactDomain tr = true) :
    ∀ c, (tr.owner c).isSome = (tr.rho c).isSome := by
  intro c
  have hc := (finiteAll_eq_true Finset.univ _).mp hcheck c
    (Finset.mem_univ c)
  exact of_decide_eq_true hc

theorem checkSourceTentative_sound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (hcheck : checkSourceTentative A tr = true) :
    ∀ c' c, tr.rho c' = some c →
      ∃ b, A.auth.status c = .tentative b := by
  intro c' c hrho
  have hc := (finiteAll_eq_true Finset.univ _).mp hcheck c'
    (Finset.mem_univ c')
  rw [hrho] at hc
  cases hs : A.auth.status c with
  | unissued => simp [checkSourceTentative, hs] at hc
  | durable => simp [checkSourceTentative, hs] at hc
  | terminal => simp [checkSourceTentative, hs] at hc
  | tentative b => exact ⟨b, rfl⟩

theorem checkProvenance_sound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (hcheck : checkProvenance A tr = true) :
    ∀ c' c, tr.rho c' = some c →
      c' = c ∨ A.auth.status c' = .unissued := by
  intro c' c hrho
  have hc := (finiteAll_eq_true Finset.univ _).mp hcheck c'
    (Finset.mem_univ c')
  rw [hrho] at hc
  exact of_decide_eq_true hc

theorem checkNoMixedFiber_sound (tr : Transfer Claim Branch)
    (hcheck : checkNoMixedFiber tr = true) :
    ∀ c, tr.rho c = some c →
      ∀ c', tr.rho c' = some c → c' = c := by
  intro c hretained c' hrho
  have hc := (finiteAll_eq_true Finset.univ _).mp hcheck c
    (Finset.mem_univ c)
  simp only [hretained, if_true] at hc
  have hc' := (finiteAll_eq_true Finset.univ _).mp hc c'
    (Finset.mem_univ c')
  exact (of_decide_eq_true hc') hrho

theorem checkGrantAgreement_sound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (hcheck : checkGrantAgreement A tr = true) :
    ∀ c' c, tr.rho c' = some c → A.grantOf c' = A.grantOf c := by
  intro c' c hrho
  have hc := (finiteAll_eq_true Finset.univ _).mp hcheck c'
    (Finset.mem_univ c')
  rw [hrho] at hc
  exact of_decide_eq_true hc

theorem checkFiberDemand_sound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (hcheck : checkFiberDemand A tr = true) :
    ∀ c k,
      (∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = some c,
        A.auth.demand c' k) ≤ A.auth.demand c k := by
  intro c k
  have hc := (finiteAll_eq_true Finset.univ _).mp hcheck c
    (Finset.mem_univ c)
  have hk := (finiteAll_eq_true Finset.univ _).mp hc k
    (Finset.mem_univ k)
  exact of_decide_eq_true hk

/-- Soundness of all projection-free transfer atoms. -/
theorem checkTransferCore_sound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (hcheck : checkTransferCore A tr = true) : CoreValid A tr := by
  simp only [checkTransferCore, Bool.and_eq_true] at hcheck
  rcases hcheck with ⟨⟨⟨⟨⟨hdomain, hsource⟩, hprovenance⟩, hmix⟩,
    hgrant⟩, hfiber⟩
  exact {
    exact_domain := checkExactDomain_sound tr hdomain
    source_tentative := checkSourceTentative_sound A tr hsource
    provenance := checkProvenance_sound A tr hprovenance
    retained_fiber_exact := checkNoMixedFiber_sound tr hmix
    grant_agreement := checkGrantAgreement_sound A tr hgrant
    fiber_demand := checkFiberDemand_sound A tr hfiber
  }

theorem checkOwnerProjection_sound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (project : Finset Branch → Finset Branch)
    (hcheck : checkOwnerProjection A tr project = true) :
    ∀ c' c b' b, tr.rho c' = some c → tr.owner c' = some b' →
      A.auth.status c = .tentative b → b ∈ project {b'} := by
  intro c' c b' b hrho howner hsource
  have hc := (finiteAll_eq_true Finset.univ _).mp hcheck c'
    (Finset.mem_univ c')
  simp [hrho, howner, hsource] at hc
  exact hc

/-- The atomized executable checker implies the full transfer contract. -/
theorem checkTransfer_sound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (project : Finset Branch → Finset Branch)
    (hcheck : checkTransfer A tr project = true) : Valid A tr project := by
  have hparts : checkTransferCore A tr = true ∧
      checkOwnerProjection A tr project = true := by
    simpa [checkTransfer] using hcheck
  exact {
    toCoreValid := checkTransferCore_sound A tr hparts.1
    owner_projection := checkOwnerProjection_sound A tr project hparts.2
  }

/-- The computed target is tentative exactly on the common `rho`/owner
domain, with the owner named by the transfer. -/
theorem targetStatus_tentative_iff
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (c : Claim) (b : Branch) :
    tr.targetStatus A c = .tentative b ↔
      ∃ source, tr.rho c = some source ∧ tr.owner c = some b := by
  cases hrho : tr.rho c with
  | none =>
      cases howner : tr.owner c with
      | none =>
          cases hstatus : A.auth.status c <;>
            simp [targetStatus, hrho, howner, hstatus]
      | some owner =>
          cases hstatus : A.auth.status c <;>
            simp [targetStatus, hrho, howner, hstatus]
  | some source =>
      cases howner : tr.owner c with
      | none =>
          cases hstatus : A.auth.status c <;>
            simp [targetStatus, hrho, howner, hstatus]
      | some owner =>
          simp [targetStatus, hrho, howner]

/-- Under a successful core check, target tentativeness has exactly the
`rho` domain; no malformed one-sided entry is silently admitted. -/
theorem targetStatus_tentative_exists_iff
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (hvalid : CoreValid A tr) (c : Claim) :
    (∃ b, tr.targetStatus A c = .tentative b) ↔
      ∃ source, tr.rho c = some source := by
  rw [exists_congr fun b => targetStatus_tentative_iff A tr c b]
  constructor
  · rintro ⟨b, source, hrho, -⟩
    exact ⟨source, hrho⟩
  · rintro ⟨source, hrho⟩
    have hrhoSome : (tr.rho c).isSome = true := by simp [hrho]
    have hownerSome : (tr.owner c).isSome = true := by
      rw [hvalid.exact_domain c]
      exact hrhoSome
    obtain ⟨b, howner⟩ := Option.isSome_iff_exists.mp hownerSome
    exact ⟨b, source, hrho, howner⟩

theorem owner_eq_none_iff_rho_eq_none
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (hvalid : CoreValid A tr) (c : Claim) :
    tr.owner c = none ↔ tr.rho c = none := by
  constructor
  · intro howner
    cases hrho : tr.rho c with
    | none => rfl
    | some source =>
        have hdomain := hvalid.exact_domain c
        simp [howner, hrho] at hdomain
  · intro hrho
    cases howner : tr.owner c with
    | none => rfl
    | some b =>
        have hdomain := hvalid.exact_domain c
        simp [howner, hrho] at hdomain

theorem rho_eq_none_of_durable
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (hvalid : CoreValid A tr) (c : Claim)
    (hstatus : A.auth.status c = .durable) : tr.rho c = none := by
  cases hrho : tr.rho c with
  | none => rfl
  | some source =>
      rcases hvalid.provenance c source hrho with hsame | hfresh
      · subst source
        obtain ⟨b, htentative⟩ := hvalid.source_tentative c c hrho
        rw [hstatus] at htentative
        contradiction
      · rw [hstatus] at hfresh
        contradiction

theorem rho_eq_none_of_terminal
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (hvalid : CoreValid A tr) (c : Claim)
    (hstatus : A.auth.status c = .terminal) : tr.rho c = none := by
  cases hrho : tr.rho c with
  | none => rfl
  | some source =>
      rcases hvalid.provenance c source hrho with hsame | hfresh
      · subst source
        obtain ⟨b, htentative⟩ := hvalid.source_tentative c c hrho
        rw [hstatus] at htentative
        contradiction
      · rw [hstatus] at hfresh
        contradiction

/-- Durable claim history is definitionally preserved by a valid transfer. -/
theorem targetStatus_durable_iff
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (hvalid : CoreValid A tr) (c : Claim) :
    tr.targetStatus A c = .durable ↔ A.auth.status c = .durable := by
  constructor
  · intro htarget
    cases hrho : tr.rho c with
    | none =>
        have howner : tr.owner c = none :=
          (owner_eq_none_iff_rho_eq_none A tr hvalid c).2 hrho
        cases hsource : A.auth.status c <;>
          simp [targetStatus, hrho, howner, hsource] at htarget ⊢
    | some source =>
        have hownerSome : (tr.owner c).isSome = true := by
          rw [hvalid.exact_domain c]
          simp [hrho]
        obtain ⟨b, howner⟩ := Option.isSome_iff_exists.mp hownerSome
        simp [targetStatus, hrho, howner] at htarget
  · intro hsource
    have hrho := rho_eq_none_of_durable A tr hvalid c hsource
    have howner := (owner_eq_none_iff_rho_eq_none A tr hvalid c).2 hrho
    simp [targetStatus, hrho, howner, hsource]

/-- A terminal ID remains terminal and cannot be reused as a fragment. -/
theorem targetStatus_terminal_of_terminal
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (hvalid : CoreValid A tr) (c : Claim)
    (hstatus : A.auth.status c = .terminal) :
    tr.targetStatus A c = .terminal := by
  have hrho := rho_eq_none_of_terminal A tr hvalid c hstatus
  have howner := (owner_eq_none_iff_rho_eq_none A tr hvalid c).2 hrho
  simp [targetStatus, hrho, howner, hstatus]

/-- An old tentative ID not retained as itself is terminalized.  Provenance
prevents that issued ID from masquerading as a fresh fragment of another
claim. -/
theorem targetStatus_terminal_of_unretained_tentative
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (hvalid : CoreValid A tr) (c : Claim)
    (b : Branch) (hstatus : A.auth.status c = .tentative b)
    (hunretained : tr.rho c ≠ some c) :
    tr.targetStatus A c = .terminal := by
  have hrho : tr.rho c = none := by
    cases hr : tr.rho c with
    | none => rfl
    | some source =>
        rcases hvalid.provenance c source hr with hsame | hfresh
        · subst source
          exact (hunretained hr).elim
        · rw [hstatus] at hfresh
          contradiction
  have howner := (owner_eq_none_iff_rho_eq_none A tr hvalid c).2 hrho
  simp [targetStatus, hrho, howner, hstatus]

/-- Valid transfer leaves the durable component of load unchanged. -/
theorem targetCore_durableLoad
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (hvalid : CoreValid A tr)
    (allowed : Finset (Finset Branch)) (k : Coord) :
    (tr.targetCore A allowed).durableLoad k = A.auth.durableLoad k := by
  unfold State.durableLoad State.durableClaims
  apply Finset.sum_congr
  · ext c
    simp only [Finset.mem_filter, Finset.mem_univ, true_and, targetCore]
    exact targetStatus_durable_iff A tr hvalid c
  · intro c hc
    rfl

/-- Checked fiber conservation is load-bearing: it derives conditional-load
simulation for every target configuration from the local owner atom and the
canonical projection's monotonicity.  No per-configuration simulation is
checked separately. -/
theorem topology_fiber_conservation
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch)
    (project : Finset Branch → Finset Branch)
    (hcheck : checkTransfer A tr project = true)
    (hmono : Monotone project)
    (allowed : Finset (Finset Branch)) (C' : Finset Branch) (k : Coord) :
    (tr.targetCore A allowed).conditionalLoad C' k ≤
      A.auth.conditionalLoad (project C') k := by
  classical
  let targetClaims := (tr.targetCore A allowed).conditionalClaims C'
  let sourceClaims := A.auth.conditionalClaims (project C')
  let sourceOptions : Finset (Option Claim) := sourceClaims.image some
  have hvalid := checkTransfer_sound A tr project hcheck
  have hsubset : targetClaims ⊆
      Finset.univ.filter fun c' => tr.rho c' ∈ sourceOptions := by
    intro c' hc'
    have htarget : c' ∈ (tr.targetCore A allowed).conditionalClaims C' := hc'
    simp only [State.conditionalClaims, Finset.mem_filter, Finset.mem_univ,
      true_and] at htarget
    cases hs : tr.targetStatus A c' with
    | unissued => simp [targetCore, hs] at htarget
    | durable => simp [targetCore, hs] at htarget
    | terminal => simp [targetCore, hs] at htarget
    | tentative b' =>
        have hb'C : b' ∈ C' := by simpa [targetCore, hs] using htarget
        obtain ⟨c, hrho, howner⟩ :=
          (targetStatus_tentative_iff A tr c' b').1 hs
        obtain ⟨b, hsource⟩ := hvalid.source_tentative c' c hrho
        have hbSingleton : b ∈ project {b'} :=
          hvalid.owner_projection c' c b' b hrho howner hsource
        have hbProject : b ∈ project C' :=
          hmono (Finset.singleton_subset_iff.mpr hb'C) hbSingleton
        have hcSource : c ∈ sourceClaims := by
          simp [sourceClaims, State.conditionalClaims, hsource, hbProject]
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
  unfold State.conditionalLoad
  change (∑ c' ∈ targetClaims, A.auth.demand c' k) ≤
    ∑ c ∈ sourceClaims, A.auth.demand c k
  calc
    (∑ c' ∈ targetClaims, A.auth.demand c' k)
        ≤ ∑ c' ∈ Finset.univ.filter
            (fun c' => tr.rho c' ∈ sourceOptions), A.auth.demand c' k :=
      Finset.sum_le_sum_of_subset hsubset
    _ = ∑ source ∈ sourceOptions,
          ∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = source,
            A.auth.demand c' k := hfiberwise
    _ = ∑ c ∈ sourceClaims,
          ∑ c' ∈ Finset.univ.filter fun c' => tr.rho c' = some c,
            A.auth.demand c' k := hreindex
    _ ≤ ∑ c ∈ sourceClaims, A.auth.demand c k := by
      exact Finset.sum_le_sum fun c hc => hvalid.fiber_demand c k

end Transfer

end AuthorityContinuity
