# CSF 2027 blind-read attack map

## Scope and contamination disclosure

This is a read-only review of the submission PDF/source after the citation and
implementation-claim repairs. I had previously seen parts of the Lean
strengthening work, so this is not a literally unprimed blind review. I first
read the complete paper without consulting project intent/history, then audited
the formal definitions and outside work.

## Initial acceptance case

The paper is in scope for CSF, professionally presented, explicit about its
threat model and nonclaims, and backed by a substantial Lean development. The
three-plane distinction is clear, the zero-demand example is easy to
understand, and the paper does not falsely claim exactly-once external effects,
native Codex/Claude refinement, dynamic plan installation, or safety rates from
trajectory data. There is no evident format, anonymity, ethics, or foundational
content reason for desk rejection.

## Acceptance-critical attack map

1. **Necessity of occurrence linearity is not established.** The paper proves
   that its eager controller representation has at most one current claim per
   token, but does not show that effect safety requires this stronger property.
   A simpler monitor can let arbitrarily many branches carry aliases of one
   token and use a global atomic compare-and-swap at `Prepare` so that exactly
   one alias obtains a ticket. That execution violates `Linear` before
   promotion while still satisfying bounded use and at-most-one durable effect.
   Because this paper already assumes one nonrollbackable serialized monitor,
   atomic `Prepare`, and complete mediation, this is not an unavailable
   baseline.

2. **The headline exactness theorem is definitionally close.** `NonAmp` is
   defined as cardinality at most one of `transferCurrentFiber`; the target
   theorem first proves by extensional simplification that this set equals the
   target `currentFiber`, then rewrites the same bound. The canonical and Merge
   cases instantiate a reflexive remaining-batch equality. The result is
   correct and executable, but it is not yet a nontrivial characterization of
   a security boundary. Stable-origin preservation is likewise induced by
   constructors that preserve `opClaim` and forbid durable claims from `rho`.
   Mechanization increases confidence, not theoretical depth.

3. **The agent-specific hard boundary is assumed rather than realized.** The
   trusted adapter must truthfully classify the history operation and supply
   the actual semantic lineage map `rho`; complete tool mediation is assumed;
   plan-epoch installation, global freshness, and cross-epoch reconciliation
   are outside the transition system. The only Codex connection is a
   client-owned effect callback, not native Fork/Restore/Merge integration, and
   the trace study confirms that ordinary telemetry lacks the required fields.
   Thus the prototype validates the easy vertical ticket gate while leaving the
   security-critical horizontal history-to-authority mapping in the TCB.

These three attacks are coupled: without a separation from atomic redemption,
the stronger pre-promotion invariant may be unnecessary; without a deeper
theorem, the model looks by-construction; without a real lineage refinement,
its extra restriction has no demonstrated runtime benefit.

