import AuthorityContinuity.Audit
import AuthorityContinuity.PlanTokenStrengthening
import AuthorityContinuity.TokenWeightedAccounting
import AuthorityContinuity.ConfigurationCellQuotient
import AuthorityContinuity.CoordinationDecomposition
import AuthorityContinuity.DurablePrefixTransport
import AuthorityContinuity.RedemptionCommitment
import AuthorityContinuity.RedemptionDomainFrontier

/-!
# Authority Continuity

This is the replay root for the finite RQ3 mechanization.  Importing it
elaborates the executable checker, exact restriction and Prepare construction,
computed canonical Fork/Restore targets, checked simulation/direct Merge,
the single closed lifecycle relation, separating witnesses, temporal
non-resurrection results, labeled concrete simulation, effect coverage, and
the conditional trace theorem.  It also replays source-derived token
non-amplification, durable operation-token continuity, and epoch-qualified
identity/weighted accounting for the token-aware plan grammar.
It additionally replays the general redemption-domain upper bound, the
availability/independence-conditional tight frontier, its independent-domain
specialization, and three separating lifecycle examples.  The classical
configuration-morphism bridge is replayed separately: it establishes the exact
finite additive certificate while deliberately making no novelty claim for
local injectivity or configuration preservation themselves.
The exact coordination module characterizes candidate controller partitions by
minimal nonfaces and identifies their connected-component closure as the
least common-coordination equivalence under maximal asynchronous `localProduct`
recombination, whose classes give the finest exact partition up to block-label
renaming.  Physical co-location is not implied.  Its static combinatorics are
classical supporting machinery; the checked output is intended to drive a
later typed Fork/Restore/Merge compiler.
The durable-prefix module composes that spatial decomposition with immutable
receipt history.  It characterizes prefix-sensitive transport, computes the
greatest safe pruning of a fixed future family, checks whether typed required
behaviors survive that pruning, and derives the finest exact controller
partition for the admitted future.
The operational commitment core separately derives unit-atom conservation,
ledger/phase monotonicity, and exact fresh-event accounting for
Prepare/Replay/Retry/Crash/Settle.  Fork/Restore/Merge preservation remains a
separate topology-refinement obligation and is not claimed by this replay root.

`AuthorityContinuity.Audit` prints the kernel dependencies of every
paper-facing theorem.  Boundary I/II and concrete product-runtime refinement
are deliberately outside this root's mechanized scope.
-/
