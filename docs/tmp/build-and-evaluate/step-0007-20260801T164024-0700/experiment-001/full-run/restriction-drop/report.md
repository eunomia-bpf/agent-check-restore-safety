# Restriction/Revoke plan transport report

## Result

**PASS.**  The repository's real authority restriction, and its real
grant-epoch Revoke specialization, admit a computed multi-slot plan transport
from source invariants alone.  The implementation is
`lean/AuthorityContinuity/PlanInvariantDrop.lean` at SHA-256
`e288da9813c8a22c2447e2a3b0fcb8109f9c62544f39dc2e22ce4885b11b0f67`.

No honest narrowing was needed for generic restriction.  The result covers
arbitrary retained owner and claim sets, so the authority-deletion portion is
strictly more general than grant Revoke.

## Computed transition

For source lifecycle `A`, plan `p`, retained owners `S`, and retained claim IDs
`keep`, the exact target lifecycle is the existing executable definition
`restrictLifecycle A S keep`.  The target plan `afterRestriction` is computed
as follows:

- `version := p.version + 1`;
- `remaining` is filtered by whether each old selected claim is still
  tentative in that exact target lifecycle;
- `slots`, `rootSlot`, `d0`, `cap0`, `R`, `P`, and `E` are unchanged.

Keeping the other rows unchanged is semantic, not a convenience:
`restrictStateBy` preserves capacity, demand, and durable claims exactly.
Restriction can therefore only lower live tentative load `L` and remaining
batch load `B`; it creates no durable exposure that would require an `E`
update.

## Main proof chain

The module proves, without a target-validity/readiness premise:

1. target tentative claims retain the same source owner;
2. target `remaining`, every root fiber, tentative-root claims, and active
   `(slot, owner)` groups are subsets of their source counterparts;
3. the recomputed lexicographic cursor cannot move to an earlier slot;
4. `L` and `B` decrease pointwise;
5. `DurableEq`, `Envelope`, `Deadline`, `BatchBound`, and `CursorPhase` all
   survive; and
6. all structural fields of `PlanData.Valid` are reconstructed from source
   `Valid`.

The paper-facing endpoints are:

- `afterRestriction_preserves_valid`;
- `afterRestriction_actual_step`, which constructs the actual
  `Step.core (CoreStep.restriction ...)`;
- `afterRestriction_preserves_all`, which also derives target LWF, AC, and
  ActiveExact;
- `RestrictionPlanned`, whose sole admission guard is the executable durable
  version CAS `checkVersion offered = true`; and
- `RestrictionPlanned.preserves_all` plus version soundness/successor lemmas.

## Revoke specialization

`afterRevoke` instantiates the same computed drop with all owners retained and
the real Revoke keep-set `{c | A.grantOf c != g}`.  Its paired lifecycle target
is exactly `revokeState A g`, and the actual step is
`Step.core (CoreStep.revoke A g)`.

The plan invariant depends only on the authority projection, so a proved
`Valid.transport_auth` bridge transfers the generic restriction result across
Revoke's additional update of `grantEpoch g` to `closed`.  Lifecycle LWF, AC,
and ActiveExact for that epoch update come from the existing actual-step
preservation theorem, not from the plan invariant.

`RevokePlanned` then adds the same executable version CAS to this exact target;
its soundness, version-successor, actual-step, target-validity, and combined
preservation theorems all compile independently of the generic relation.

## Claim boundary

- This proves safe controller transport for **deletion** operations.  It does
  not prove that an arbitrary addition, root reassignment, or cross-slot Merge
  may leave the schedule unchanged.
- `PlanData.Valid` intentionally does not specify grant/branch epoch policy;
the combined `preserves_all` endpoints pair it with LWF/AC/ActiveExact, which
do carry those obligations.
- Restriction itself has no semantic readiness guard in the lifecycle kernel.
  Both paper-facing controller relations, `RestrictionPlanned` and
  `RevokePlanned`, nevertheless use version CAS to reject stale concurrent
  mutations.
- The result proves invariant preservation, not that a chosen restriction is
  desirable for application-level liveness.  A restriction may legitimately
  delete the entire remaining batch.

## Validation

- pinned Lean 4.30.0 Lake build: pass;
- fresh `leanchecker --fresh`: pass;
- forbidden proof scan (`sorry`, `admit`, `native_decide`, custom `axiom`):
  clean;
- readiness/target-oracle premise scan: clean;
- axiom allowlist: only `propext`, `Classical.choice`, and `Quot.sound`.
