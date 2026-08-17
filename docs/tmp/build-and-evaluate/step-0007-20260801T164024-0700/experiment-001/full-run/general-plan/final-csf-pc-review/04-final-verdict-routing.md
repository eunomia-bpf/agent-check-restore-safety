# Final CSF 2027 verdict and routing

## Verdict

**Weak Reject (borderline); recommend Major Revision if the CSF cycle offers
that decision. Confidence: 4/5.**

There is no apparent desk-reject condition. The work is relevant, readable,
ethically disclosed, and technically careful. The likely rejection is on
originality/significance: the paper mechanizes a defensible monitor invariant,
but has not shown that this invariant is the necessary agent-security boundary
or that its main theorem is deep enough for CSF.

| Dimension | Assessment | Reason |
|---|---:|---|
| Originality | 2/5 | Exact history-operator instantiation may be new, but copyable evidence plus bounded atomic ratification is established and the 2005 VM lifecycle predecessor is missing. |
| Technical correctness | 4/5 | Statements match the Lean model under explicit assumptions; no major proof/paper mismatch found. |
| Significance | 2/5 | `currentFiber` exactness is close to definitional, and the stronger pre-promotion invariant is not separated from a simpler redemption-only monitor. |
| Presentation | 4/5 | Clear organization, readable 11-page PDF, careful nonclaims. |
| Evidence | 2.5/5 | Lean is strong evidence for the model; runtime evidence does not instantiate native lineage/topology or cross-epoch behavior. |
| Ethics | 4/5 | Private trajectory is narrowly claimed and handled with explicit minimization/non-release controls. |

## Three blocking questions a PC member can ask

1. **Why is `|cur(t)| <= 1` necessary?** Give a trace where aliases plus one
   durable atomic one-use ratifier are effect-unsafe, or prove a separation
   under explicit availability/eligibility requirements. Otherwise the slogan
   should be weakened to “authority may be copied as references, but redeemed
   once,” which is already established.

2. **Where is the nontrivial theorem?** The current iff rewrites the definition
   of `NonAmp` through `afterTransfer_currentFiber_eq`; the history theorem
   follows constructors that preserve bindings. A CSF-level revision needs a
   deeper result such as necessity and sufficiency, maximal permissiveness,
   compositional conservation over arbitrary history DAGs, a real
   cross-epoch theorem, or a refinement theorem from authenticated runtime
   events to `rho`.

3. **Who establishes semantic lineage in a deployed agent?** The paper trusts
   exactly the typed Fork/Restore/Merge classification and lineage map that its
   own trace audit says current runtimes do not expose. A native Codex/Claude or
   framework adapter should derive/attest these events and exercise structural
   transitions plus `Prepare` under crashes; otherwise the industrial algorithm
   remains an abstract reference monitor with an oracle adapter.

## What is not a blocker

- The private paper-formation trace is anecdotal but honestly scoped; do not
  attack it as safety evidence the paper never claims.
- The proof package appears aligned with the revised prose; do not frame the
  decision as formal unsoundness.
- The lack of broad performance experiments is not fatal for this theory-led
  CSF paper. The missing evidence is semantic refinement/necessity, not another
  benchmark table.

## Minimum credible revision route

The highest-value change is not prose polish. Add one formal comparison with a
redemption-only ratifier and prove precisely when eager occurrence transport is
strictly required (or concede it is a refinement for eligibility/liveness,
then make that property the theorem). Pair this with a trustworthy lineage
adapter/refinement and cite the HotOS 2005 predecessor. If that separation
cannot be proved, the current token story is better positioned as one mechanism
inside the project's stronger capability-factorization/serializability theory,
not as the standalone breakthrough.

