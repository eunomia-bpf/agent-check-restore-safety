import AuthorityContinuity.PlanTokenLinearity
import AuthorityContinuity.FullPlanInvariant

/-!
Independent, review-only audit obligations for the discrete token extension.
This file is intentionally outside the package source tree.
-/

namespace IndependentTokenAudit

open AuthorityContinuity LifecycleState
open AuthorityContinuity.PlanTokenLinearity

universe uC uI uB uG uO uS uT

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO} {Slot : Type uS}
variable {Token : Type uT}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [LinearOrder Claim]
variable [Fintype Branch] [LinearOrder Branch]
variable [DecidableEq Grant] [Fintype Operation] [DecidableEq Operation]
variable [Fintype Slot] [LinearOrder Slot]
variable [Fintype Token] [LinearOrder Token]

/-- The apparent global-`rho` attack cannot affect an actually bound durable
claim under the base lifecycle and transfer invariants. -/
theorem bound_durable_rho_none
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (hWF : A.LWF)
    (hCore : Transfer.CoreValid A tr) {e : Operation} {c : Claim}
    (hop : A.opClaim e = some c) :
    tr.rho c = none := by
  exact Transfer.rho_eq_none_of_durable A tr hCore c
    (hWF.bound_durable e c hop)

/-- Therefore `afterTransfer` retains the token origin of every existing
ticket/receipt claim.  The target controller is arbitrary here; the fact is
about the ledger update itself. -/
theorem bound_durable_origin_survives_afterTransfer
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (target : AuthorityContinuity.PlanInvariant.PlanData.InvariantState
      (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (ledger : TokenLedger Claim Token)
    (tr : Transfer Claim Branch) (hWF : A.LWF)
    (hCore : Transfer.CoreValid A tr) {e : Operation} {c : Claim}
    (hop : A.opClaim e = some c) :
    (ledger.afterTransfer target tr).origin c = ledger.origin c := by
  have hrho : tr.rho c = none :=
    bound_durable_rho_none A tr hWF hCore hop
  simp [TokenLedger.afterTransfer, TokenLedger.reclassify,
    TokenLedger.transportedOrigin, hrho]

/-! A target-only repair witness.  The combined Restriction Boolean does not
test source `LinearValid`: it accepts a source already made token-invalid by
the unchecked zero-demand fork once Restriction removes one duplicate.  This
does not refute `TokenPositiveTrace` preservation, whose source is `TokenSafe`;
it fixes the exact interpretation of the admission checker. -/

namespace TargetOnlyRepair

open AuthorityContinuity.PlanTokenLinearity.ZeroDemandRegression

def invalidSource := advanceCanonical state split fork

theorem invalid_source_rejected : invalidSource.checkLinear = false := by
  decide

theorem invalid_source_has_two_current_witnesses :
    (invalidSource.currentFiber 0).card = 2 := by
  decide

theorem invalid_source_not_linear : ¬ invalidSource.LinearValid := by
  intro hLinear
  have hAtMostOne := hLinear.current_linear 0 (by decide)
  rw [invalid_source_has_two_current_witnesses] at hAtMostOne
  omega

theorem target_only_restriction_accepts :
    checkRestrictionTokenPlan invalidSource ({1} : Finset ZBranch)
      ({1} : Finset ZClaim) 1 = true := by
  decide

theorem repaired_target_accepts :
    (advanceRestrictionToken invalidSource ({1} : Finset ZBranch)
      ({1} : Finset ZClaim)).checkLinear = true := by
  decide

end TargetOnlyRepair

#print axioms bound_durable_rho_none
#print axioms bound_durable_origin_survives_afterTransfer
#print axioms TargetOnlyRepair.target_only_restriction_accepts
#print axioms TargetOnlyRepair.invalid_source_not_linear
#print axioms AuthorityContinuity.PlanTokenLinearity.TokenState.LinearValid.token_trichotomy
#print axioms AuthorityContinuity.FullPlanInvariant.FullPlan.afterPrepare_exact

end IndependentTokenAudit
