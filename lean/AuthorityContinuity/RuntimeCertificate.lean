import Mathlib

/-!
# Runtime Certificate semantics

This module models the bounded semantics implemented by the Go runtime without
reusing the older Agent-history checker. A `History` contains settled facts and
the Operations whose outcomes are still unknown. A `Requirement` gives result
lower bounds, resource upper bounds, and the registered Operation kinds. Every
subset of the unknown Operations is one possible world.

`Completable` is deliberately finite: a completion contains at most the total
number of still requested result units. This matches the runtime search, which
never takes an Operation that advances no missing result. The Go-to-Lean wire
normalization, JSON encoding, SHA-256 binding, and resource-limit agreement are
separate refinement obligations; the theorems here do not claim them.
-/

namespace AuthorityContinuity.RuntimeCertificate

open scoped BigOperators

universe uResult uResource uKind uOperation

/-- Results and capacities requested after a change, plus the frozen meaning
of every Operation kind available to complete them. -/
structure Requirement (Result : Type uResult) (Resource : Type uResource)
    (Kind : Type uKind) where
  results : Result → Nat
  capacities : Resource → Nat
  costs : Kind → Resource → Nat
  produces : Kind → Result → Nat
  retrySafe : Kind → Bool

/-- Additive facts already forced by settled or assumed-successful Operations. -/
structure Facts (Result : Type uResult) (Resource : Type uResource) where
  used : Resource → Nat
  produced : Result → Nat

/-- Frozen meaning of an Operation whose outcome can still affect the answer. -/
structure Operation (Result : Type uResult) (Resource : Type uResource) where
  costs : Resource → Nat
  produces : Result → Nat
  retrySafe : Bool

/-- The normalized History input used by the bounded checker. -/
structure History (Result : Type uResult) (Resource : Type uResource)
    (OperationId : Type uOperation) where
  settled : Facts Result Resource
  openOperations : Finset OperationId
  operation : OperationId → Operation Result Resource

/-- A Rule is exactly the set of Operation kinds enabled after activation. -/
structure Rule (Kind : Type uKind) where
  allow : Finset Kind

/-- The semantic part of schema-1 Certificate decisions. Encoding fields are
handled by the separate wire-integrity layer. -/
inductive Certificate (Kind : Type uKind) where
  | activate (rule : Rule Kind)
  | impossible

section FiniteModel

variable {Result : Type uResult} {Resource : Type uResource}
variable {Kind : Type uKind} {OperationId : Type uOperation}
variable [Fintype Result] [DecidableEq Result]
variable [Fintype Resource] [DecidableEq Resource]
variable [Fintype Kind] [DecidableEq Kind]
variable [Fintype OperationId] [DecidableEq OperationId]

/-- Total requested result units. The Go model rejects values above its public
bound before invoking the exact search. -/
def Requirement.totalResults (requirement : Requirement Result Resource Kind) : Nat :=
  ∑ result : Result, requirement.results result

/-- Facts in the world where exactly `succeeded` among the open Operations
eventually committed. -/
def History.afterWorld (history : History Result Resource OperationId)
    (succeeded : Finset OperationId) : Facts Result Resource where
  used := fun resource =>
    history.settled.used resource +
      ∑ operation ∈ succeeded, (history.operation operation).costs resource
  produced := fun result =>
    history.settled.produced result +
      ∑ operation ∈ succeeded, (history.operation operation).produces result

/-- Apply the success outcome of one newly allowed Operation kind. -/
def Requirement.afterKind (requirement : Requirement Result Resource Kind)
    (facts : Facts Result Resource) (kind : Kind) : Facts Result Resource where
  used := fun resource => facts.used resource + requirement.costs kind resource
  produced := fun result =>
    facts.produced result + requirement.produces kind result

/-- One bounded completion plan satisfies the Requirement from the supplied
facts. Its entries must all have implemented safe retry. -/
def PlanWorks (requirement : Requirement Result Resource Kind)
    (facts : Facts Result Resource) {count : Nat} (plan : Fin count → Kind) : Prop :=
  (∀ index, requirement.retrySafe (plan index) = true) ∧
  (∀ resource,
    facts.used resource +
      ∑ index : Fin count, requirement.costs (plan index) resource ≤
        requirement.capacities resource) ∧
  (∀ result,
    requirement.results result ≤
      facts.produced result +
        ∑ index : Fin count, requirement.produces (plan index) result)

/-- Some finite completion of length at most the total requested units works. -/
def Completable (requirement : Requirement Result Resource Kind)
    (facts : Facts Result Resource) : Prop :=
  ∃ count : Fin (requirement.totalResults + 1),
    ∃ plan : Fin count.val → Kind, PlanWorks requirement facts plan

instance completableDecidable
    (requirement : Requirement Result Resource Kind)
    (facts : Facts Result Resource) : Decidable (Completable requirement facts) := by
  unfold Completable PlanWorks
  infer_instance

/-- Canonical finite enumeration of all possible open-Operation outcomes. -/
def History.worlds (history : History Result Resource OperationId) :
    Finset (Finset OperationId) :=
  Finset.univ.filter fun succeeded => succeeded ⊆ history.openOperations

theorem History.mem_worlds_iff
    (history : History Result Resource OperationId)
    (succeeded : Finset OperationId) :
    succeeded ∈ history.worlds ↔ succeeded ⊆ history.openOperations := by
  simp [History.worlds]

/-- The current History can still meet the target in every possible world,
and every uncertain Operation has implemented recovery. -/
def Viable (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId) : Prop :=
  (∀ operation ∈ history.openOperations,
    (history.operation operation).retrySafe = true) ∧
  (∀ succeeded ∈ history.worlds,
    Completable requirement (history.afterWorld succeeded))

instance viableDecidable
    (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId) :
    Decidable (Viable requirement history) := by
  unfold Viable
  infer_instance

/-- A kind is safe to enable exactly when its own recovery is implemented and
its success leaves every possible world completable. -/
def SafeNext (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId) (kind : Kind) : Prop :=
  requirement.retrySafe kind = true ∧
  ∀ succeeded ∈ history.worlds,
    Completable requirement
      (requirement.afterKind (history.afterWorld succeeded) kind)

instance safeNextDecidable
    (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId) (kind : Kind) :
    Decidable (SafeNext requirement history kind) := by
  unfold SafeNext
  infer_instance

/-- The unique largest Rule: every and only individually safe next kind. -/
def canonicalRule (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId) : Finset Kind :=
  Finset.univ.filter fun kind => SafeNext requirement history kind

theorem mem_canonicalRule_iff
    (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId) (kind : Kind) :
    kind ∈ canonicalRule requirement history ↔
      SafeNext requirement history kind := by
  simp [canonicalRule]

theorem canonicalRule_safe
    (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId) :
    ∀ kind ∈ canonicalRule requirement history,
      SafeNext requirement history kind := by
  simpa [mem_canonicalRule_iff]

theorem safeRule_subset_canonical
    (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId)
    (candidate : Finset Kind)
    (safe : ∀ kind ∈ candidate, SafeNext requirement history kind) :
    candidate ⊆ canonicalRule requirement history := by
  intro kind member
  exact (mem_canonicalRule_iff requirement history kind).2 (safe kind member)

/-- Declarative correctness of one semantic Certificate decision. -/
def Correct (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId) : Certificate Kind → Prop
  | .activate rule =>
      Viable requirement history ∧
        rule.allow = canonicalRule requirement history
  | .impossible => ¬ Viable requirement history

/-- Executable finite checker for the semantic Certificate decision. -/
def verifyCertificate (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId) : Certificate Kind → Bool
  | .activate rule =>
      decide (Viable requirement history) &&
        decide (rule.allow = canonicalRule requirement history)
  | .impossible => decide (¬ Viable requirement history)

theorem verifyActivate_iff_canonicalRule
    (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId) (rule : Rule Kind) :
    verifyCertificate requirement history (.activate rule) = true ↔
      Viable requirement history ∧
        rule.allow = canonicalRule requirement history := by
  simp [verifyCertificate]

theorem verifyImpossible_iff_not_viable
    (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId) :
    verifyCertificate requirement history (.impossible : Certificate Kind) = true ↔
      ¬ Viable requirement history := by
  simp [verifyCertificate]

theorem verifyCertificate_iff_correct
    (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId)
    (certificate : Certificate Kind) :
    verifyCertificate requirement history certificate = true ↔
      Correct requirement history certificate := by
  cases certificate <;> simp [verifyCertificate, Correct]

theorem activate_and_impossible_disjoint
    (requirement : Requirement Result Resource Kind)
    (history : History Result Resource OperationId) (rule : Rule Kind) :
    ¬ (Correct requirement history (.activate rule) ∧
      Correct requirement history (.impossible : Certificate Kind)) := by
  intro both
  exact both.2 both.1.1

end FiniteModel

end AuthorityContinuity.RuntimeCertificate
