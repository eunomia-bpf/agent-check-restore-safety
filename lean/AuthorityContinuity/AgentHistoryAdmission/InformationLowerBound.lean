import Mathlib

/-!
# Representation-independent information lower bound

This module states exactness in terms of answers, not record fields.  An exact
view may use any representation, compression, or sufficient statistic, but
equal views must induce equal answers to every admission query.  The generic
separation theorem therefore applies to arbitrary view types.

The finite four-factor instance supplies independent promise (`P`), identity
(`I`), edit (`E`), and current-cut (`C`) coordinates.  Any exact view separates
all sixteen answer classes and, when finite, has at least sixteen elements.
-/

namespace AuthorityContinuity.AgentHistoryAdmission.InformationLowerBound

universe uRecord uQuery uAnswer uView

/-- Two records are equivalent exactly when every query receives the same
answer. -/
def AnswerEquivalent
    (answer : Record → Query → Answer)
    (left right : Record) : Prop :=
  ∀ query, answer left query = answer right query

/-- The representation-independent sufficient statistic of all answers. -/
def answerSignature
    (answer : Record → Query → Answer)
    (record : Record) : Query → Answer :=
  answer record

/-- A view is exact when equal views never collapse answer-distinguishable
records. -/
def ExactView
    (answer : Record → Query → Answer)
    (view : Record → View) : Prop :=
  ∀ left right, view left = view right →
    AnswerEquivalent answer left right

theorem answerSignature_exact
    (answer : Record → Query → Answer) :
    ExactView answer (answerSignature answer) := by
  intro left right same query
  exact congrFun same query

/-- Exactness is exactly refinement of answer-signature equivalence; it does
not require retention of any particular raw field representation. -/
theorem exactView_iff_refines_answerSignature
    (answer : Record → Query → Answer)
    (view : Record → View) :
    ExactView answer view ↔
      ∀ left right, view left = view right →
        answerSignature answer left = answerSignature answer right := by
  constructor
  · intro exact left right same
    funext query
    exact exact left right same query
  · intro refines left right same query
    exact congrFun (refines left right same) query

/-- Every exact representation separates every pair that some query can
distinguish. -/
theorem exactView_separates_answer_pair
    (answer : Record → Query → Answer)
    (view : Record → View)
    (exact : ExactView answer view)
    {left right : Record} {query : Query}
    (different : answer left query ≠ answer right query) :
    view left ≠ view right := by
  intro same
  exact different (exact left right same query)

/-! ## Four independent answer dimensions -/

inductive RecordDimension where
  | P
  | I
  | E
  | C
deriving DecidableEq, Repr, Fintype

/-- One Boolean coordinate for each class of execution-record fact needed by
the finite separation instance. -/
structure FourFactorRecord where
  P : Bool
  I : Bool
  E : Bool
  C : Bool
deriving DecidableEq, Repr, Fintype

def fourFactorAnswer :
    FourFactorRecord → RecordDimension → Bool
  | record, .P => record.P
  | record, .I => record.I
  | record, .E => record.E
  | record, .C => record.C

def allFalse : FourFactorRecord :=
  ⟨false, false, false, false⟩

def singleTrue : RecordDimension → FourFactorRecord
  | .P => ⟨true, false, false, false⟩
  | .I => ⟨false, true, false, false⟩
  | .E => ⟨false, false, true, false⟩
  | .C => ⟨false, false, false, true⟩

theorem fourFactorAnswer_injective :
    Function.Injective fourFactorAnswer := by
  intro left right same
  cases left with
  | mk leftP leftI leftE leftC =>
      cases right with
      | mk rightP rightI rightE rightC =>
          have p := congrFun same RecordDimension.P
          have i := congrFun same RecordDimension.I
          have e := congrFun same RecordDimension.E
          have c := congrFun same RecordDimension.C
          simp only [fourFactorAnswer] at p i e c
          cases p
          cases i
          cases e
          cases c
          rfl

/-- Any exact view is injective on the sixteen answer classes. -/
theorem fourFactor_exactView_injective
    (view : FourFactorRecord → View)
    (exact : ExactView fourFactorAnswer view) :
    Function.Injective view := by
  intro left right same
  apply fourFactorAnswer_injective
  funext dimension
  exact exact left right same dimension

theorem fourFactorRecord_card :
    Fintype.card FourFactorRecord = 16 := by
  rfl

/-- A finite exact view needs at least four bits: it has at least sixteen
distinct answer classes, regardless of its internal representation. -/
theorem fourFactor_exactView_card_lower_bound
    [Fintype View]
    (view : FourFactorRecord → View)
    (exact : ExactView fourFactorAnswer view) :
    16 ≤ Fintype.card View := by
  rw [← fourFactorRecord_card]
  exact Fintype.card_le_of_injective view
    (fourFactor_exactView_injective view exact)

/-- Each of the four coordinates has a pair that agrees on the other three
coordinates but every exact view must separate. -/
theorem exactView_separates_each_dimension
    (view : FourFactorRecord → View)
    (exact : ExactView fourFactorAnswer view) :
    ∀ dimension, view allFalse ≠ view (singleTrue dimension) := by
  intro dimension
  apply exactView_separates_answer_pair fourFactorAnswer view exact
    (query := dimension)
  cases dimension <;> decide

end AuthorityContinuity.AgentHistoryAdmission.InformationLowerBound
