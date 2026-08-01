"""Unit tests for the finite authority-continuity model."""

from __future__ import annotations

import unittest

from authority_continuity import (
    Claim,
    FrozenThresholdGuard,
    GuardTerm,
    GuardedContract,
    LifecycleRejected,
    batch_admitted_by_target,
    batch_in_residual,
    bounded_residual_derivative,
    branch_headroom,
    claims_have_owner_support,
    cleanup_unsupported_owners,
    crash_recover,
    dispatch_operation,
    downward_closure,
    enumerated_residual_profile,
    enumerate_reservation_batches,
    exact_repair_guard,
    guarded_authority_continuous,
    headroom_box_profile,
    headroom_corner_satisfies_slack,
    install_exact_repair,
    is_downward_closed,
    is_conflict_graph_representable,
    knowledge_residual_intersection,
    fork_branch,
    make_lifecycle_state,
    make_state,
    make_reservation_batch,
    owner_support_well_formed,
    plain_escape_counterexample,
    powerset,
    prepare_operations,
    promote_with_exact_guard,
    reserve_admitted_by_headroom,
    reserve_batch,
    restore_live,
    restore_replace,
    retry_operation,
    revoke_epoch,
    settle_operation,
    snapshot_local_impossibility_litmus,
    structural_history_preserved,
    vector_leq,
    withdraw_tentative,
    witnessed_promote_with_tombstones,
)


class AuthorityContinuityTests(unittest.TestCase):
    def test_ac_checks_every_vector_coordinate_and_frontier(self) -> None:
        state = make_state(
            (2, 2),
            durable=(Claim("durable", (1, 0), None),),
            conditional=(
                Claim("a-use", (1, 2), "a"),
                Claim("b-use", (0, 3), "b"),
            ),
            frontiers=downward_closure((("a",), ("b",))),
        )
        self.assertFalse(state.authority_continuous)
        self.assertEqual((2, 3), state.need)
        self.assertFalse(vector_leq(state.need, state.grant))
        self.assertEqual((1, 3), state.frontier_load(frozenset(("b",))))

    def test_ac_need_equivalence_on_safe_state(self) -> None:
        state = make_state(
            (2, 3),
            durable=(Claim("durable", (1, 0), None),),
            conditional=(
                Claim("a-use", (1, 2), "a"),
                Claim("b-use", (0, 3), "b"),
            ),
            frontiers=downward_closure((("a",), ("b",))),
        )
        enlarged = make_state(
            (2, 3),
            durable=state.durable,
            conditional=(Claim("a-use", (1, 2), "a"),),
            frontiers=state.frontiers,
        )
        self.assertTrue(enlarged.authority_continuous)
        self.assertTrue(vector_leq(enlarged.need, enlarged.grant))

    def test_plain_escape_can_break_ac(self) -> None:
        source, target, witness = plain_escape_counterexample()
        self.assertTrue(source.authority_continuous)
        self.assertFalse(target.authority_continuous)
        self.assertEqual((2,), target.frontier_load(witness))
        self.assertEqual((1,), target.grant)

    def test_single_claim_maximal_support_is_safe_and_downward_closed(self) -> None:
        source, _, _ = plain_escape_counterexample()
        repaired = source.promote_maximally(("left-use",))
        self.assertTrue(repaired.authority_continuous)
        self.assertTrue(is_downward_closed(repaired.frontiers))
        self.assertEqual(
            frozenset((frozenset(), frozenset(("left",)))),
            repaired.frontiers,
        )

    def test_batched_promotion_is_order_independent(self) -> None:
        source = make_state(
            (2,),
            conditional=(
                Claim("a-use", (1,), "a"),
                Claim("b-use", (1,), "b"),
                Claim("c-use", (1,), "c"),
            ),
            frontiers=downward_closure((("a", "b", "c"),)),
        )
        batch = source.promote_maximally(("a-use", "b-use"))
        a_then_b = source.promote_maximally(("a-use",)).promote_maximally(("b-use",))
        b_then_a = source.promote_maximally(("b-use",)).promote_maximally(("a-use",))
        self.assertEqual(batch, a_then_b)
        self.assertEqual(batch, b_then_a)

    def test_snapshot_local_worlds_require_opposite_decisions(self) -> None:
        litmus = snapshot_local_impossibility_litmus()
        self.assertEqual("same-fresh-reserve:0:restored", litmus["proposal"]["fresh_claim_id"])
        self.assertTrue(litmus["replace"]["pre"]["safe"])
        self.assertTrue(litmus["live"]["pre"]["safe"])
        self.assertEqual([], litmus["replace"]["pre"]["conditional_claim_ids"])
        self.assertEqual(["old"], litmus["live"]["pre"]["conditional_claim_ids"])
        self.assertEqual([0], litmus["replace"]["pre"]["need"])
        self.assertEqual([1], litmus["live"]["pre"]["need"])
        self.assertTrue(litmus["replace"]["successor"]["safe"])
        self.assertFalse(litmus["live"]["successor"]["safe"])
        self.assertEqual([1], litmus["replace"]["successor"]["need"])
        self.assertEqual([2], litmus["live"]["successor"]["need"])

    def test_threshold_guard_exactly_represents_u23_after_promotion(self) -> None:
        base = downward_closure((("b",), ("x", "y", "z")))
        source = make_state(
            (3,),
            conditional=(
                Claim("cb", (1,), "b"),
                Claim("cx", (1,), "x"),
                Claim("cy", (1,), "y"),
                Claim("cz", (1,), "z"),
            ),
            frontiers=base,
        )
        self.assertTrue(source.authority_continuous)
        promoted = source.promote_plain(("cb",))
        contract = install_exact_repair(promoted, GuardedContract(base), "promote-cb")

        xyz = ("x", "y", "z")
        restricted = frozenset(
            frontier for frontier in contract.support if frontier <= frozenset(xyz)
        )
        u23 = frozenset(frontier for frontier in powerset(xyz) if len(frontier) <= 2)
        self.assertEqual(u23, restricted)
        self.assertFalse(is_conflict_graph_representable(restricted, xyz))
        self.assertEqual((2,), contract.guards[0].residual)
        self.assertEqual(source.promote_maximally(("cb",)).frontiers, contract.support)

    def test_frozen_guard_does_not_reopen_after_withdraw(self) -> None:
        base = downward_closure((("b",), ("x", "y", "z")))
        source = make_state(
            (3,),
            conditional=(
                Claim("cb", (1,), "b"),
                Claim("cx", (1,), "x"),
                Claim("cy", (1,), "y"),
                Claim("cz", (1,), "z"),
            ),
            frontiers=base,
        )
        promoted = source.promote_plain(("cb",))
        frozen = install_exact_repair(promoted, GuardedContract(base), "frozen")
        triple = frozenset(("x", "y", "z"))
        self.assertNotIn(triple, frozen.support)

        withdrawn = withdraw_tentative(promoted, "cx")
        # Recomputing coefficients from current Q silently changes an earlier
        # lifecycle decision and reopens the triple.  The frozen guard does not.
        dynamic = GuardedContract(base, (exact_repair_guard(withdrawn, "dynamic"),))
        self.assertIn(triple, dynamic.support)
        self.assertNotIn(triple, frozen.support)

    def test_lineage_or_transport_charges_live_restore_once(self) -> None:
        base = downward_closure((("old",),))
        guard = FrozenThresholdGuard(
            "lineage-budget",
            (2,),
            (GuardTerm("lineage-old", (2,), frozenset(("old",))),),
        )
        transported = GuardedContract(base, (guard,)).transport_live_restore(
            "old", "restored"
        )
        pair = frozenset(("old", "restored"))
        self.assertIn(pair, transported.base_frontiers)
        self.assertEqual((2,), transported.guards[0].charge(pair))
        self.assertTrue(transported.allows(pair))

        naive_copy = FrozenThresholdGuard(
            "naive-copy",
            (2,),
            (
                GuardTerm("copy-old", (2,), frozenset(("old",))),
                GuardTerm("copy-restored", (2,), frozenset(("restored",))),
            ),
        )
        self.assertEqual((4,), naive_copy.charge(pair))
        self.assertFalse(naive_copy.allows(pair))

    def test_abstract_confluence_does_not_justify_owner_tombstoning(self) -> None:
        base = downward_closure((("a",), ("b",)))
        source = make_state(
            (2,),
            conditional=(
                Claim("ca", (1,), "a"),
                Claim("cb", (1,), "b"),
            ),
            frontiers=base,
        )
        contract = GuardedContract(base)
        batch_state, batch_contract = promote_with_exact_guard(
            source, contract, ("ca", "cb"), "batch"
        )
        self.assertTrue(
            claims_have_owner_support(
                source, ("ca", "cb"), batch_contract.support
            )
        )
        a_state, a_contract = promote_with_exact_guard(
            source, contract, ("ca",), "after-a"
        )
        serial_state, serial_contract = promote_with_exact_guard(
            a_state, a_contract, ("cb",), "after-a-b"
        )
        b_state, b_contract = promote_with_exact_guard(
            source, contract, ("cb",), "after-b"
        )
        reverse_state, reverse_contract = promote_with_exact_guard(
            b_state, b_contract, ("ca",), "after-b-a"
        )
        self.assertEqual(batch_state, serial_state)
        self.assertEqual(batch_state, reverse_state)
        self.assertEqual(
            batch_contract.support,
            serial_contract.support,
        )
        self.assertEqual(batch_contract.support, reverse_contract.support)

        # The conservative witnessed shortcut conditions on owner a and kills
        # alternative b.  cb is moved to terminal X, so the second escape is no
        # longer an enabled transition even though abstract exact repair commutes.
        witnessed = witnessed_promote_with_tombstones(source, "ca")
        self.assertEqual(frozenset(("b",)), witnessed.tombstoned_branches)
        self.assertEqual(frozenset(("cb",)), witnessed.terminal_claim_ids)
        with self.assertRaisesRegex(ValueError, "not tentative"):
            witnessed.state.promote_plain(("cb",))

    def test_exact_serialization_absent_final_owner_support(self) -> None:
        base = downward_closure((("s",), ("t",)))
        source = make_state(
            (2,),
            conditional=(
                Claim("cs", (1,), "s"),
                Claim("ct", (1,), "t"),
                Claim("u", (1,), "t"),
            ),
            frontiers=base,
        )
        contract = GuardedContract(base)
        atomic_state, atomic_contract = promote_with_exact_guard(
            source, contract, ("cs", "ct"), "atomic"
        )
        self.assertFalse(
            claims_have_owner_support(
                source, ("cs", "ct"), atomic_contract.support
            )
        )
        atomic_cleanup = cleanup_unsupported_owners(
            atomic_state, atomic_contract.support
        )
        self.assertEqual(frozenset(("t",)), atomic_cleanup.tombstoned_branches)
        self.assertEqual(frozenset(("u",)), atomic_cleanup.terminal_claim_ids)

        s_state, s_contract = promote_with_exact_guard(
            source, contract, ("cs",), "s-first"
        )
        s_cleanup = cleanup_unsupported_owners(s_state, s_contract.support)
        self.assertEqual(frozenset(("ct", "u")), s_cleanup.terminal_claim_ids)
        with self.assertRaisesRegex(ValueError, "not tentative"):
            promote_with_exact_guard(
                s_cleanup.state, s_contract, ("ct",), "s-then-t"
            )

        t_state, t_contract = promote_with_exact_guard(
            source, contract, ("ct",), "t-first"
        )
        self.assertTrue(owner_support_well_formed(t_state, t_contract.support))
        final_state, final_contract = promote_with_exact_guard(
            t_state, t_contract, ("cs",), "t-then-s"
        )
        final_cleanup = cleanup_unsupported_owners(
            final_state, final_contract.support
        )
        self.assertEqual(atomic_contract.support, final_contract.support)
        self.assertEqual(atomic_cleanup.state, final_cleanup.state)

    def test_owner_support_is_explicit_well_formedness(self) -> None:
        supported = make_state(
            (1,),
            conditional=(Claim("c", (1,), "live"),),
            frontiers=downward_closure((("live",),)),
        )
        unsupported = make_state(
            (1,),
            conditional=(Claim("c", (1,), "ghost"),),
            frontiers=downward_closure((("live",),)),
        )
        self.assertTrue(owner_support_well_formed(supported))
        self.assertFalse(owner_support_well_formed(unsupported))

    def test_exact_guarded_repair_membership_invariant(self) -> None:
        base = downward_closure((("a", "b", "c"),))
        target = make_state(
            (3, 2),
            durable=(Claim("d", (1, 0), None),),
            conditional=(
                Claim("ca", (1, 1), "a"),
                Claim("cb", (1, 1), "b"),
                Claim("cc", (1, 1), "c"),
            ),
            frontiers=base,
        )
        contract = install_exact_repair(target, GuardedContract(base), "vector")
        for frontier in base:
            expected = vector_leq(target.frontier_load(frontier), target.grant)
            self.assertEqual(expected, contract.allows(frontier))
        self.assertTrue(guarded_authority_continuous(target, contract))
        self.assertTrue(is_downward_closed(contract.support))

    def test_single_reserve_matches_branch_headroom(self) -> None:
        state = make_state(
            (2, 3),
            durable=(Claim("d", (1, 0), None),),
            frontiers=downward_closure((("a", "b"),)),
        )
        self.assertEqual((1, 3), branch_headroom(state, "a"))
        self.assertIsNone(branch_headroom(state, "missing"))
        for weight, expected in (
            ((1, 3), True),
            ((2, 0), False),
            ((0, 4), False),
        ):
            batch = make_reservation_batch((("a", weight),))
            self.assertEqual(expected, reserve_admitted_by_headroom(state, "a", weight))
            self.assertEqual(expected, batch_admitted_by_target(state, batch))

    def test_choice_parallel_have_equal_headroom_but_different_residuals(self) -> None:
        branches = ("b1", "b2")
        choice = make_state(
            (1,),
            frontiers=downward_closure((("b1",), ("b2",))),
        )
        parallel = make_state(
            (1,),
            frontiers=downward_closure((("b1", "b2"),)),
        )
        self.assertEqual((1,), branch_headroom(choice, "b1"))
        self.assertEqual((1,), branch_headroom(parallel, "b1"))
        self.assertEqual((1,), branch_headroom(choice, "b2"))
        self.assertEqual((1,), branch_headroom(parallel, "b2"))

        both = make_reservation_batch((("b1", (1,)), ("b2", (1,))))
        self.assertTrue(batch_in_residual(choice, both))
        self.assertFalse(batch_in_residual(parallel, both))
        choice_residual = enumerated_residual_profile(choice, branches, 1)
        parallel_residual = enumerated_residual_profile(parallel, branches, 1)
        self.assertNotEqual(choice_residual, parallel_residual)
        self.assertTrue(headroom_corner_satisfies_slack(choice, branches))
        self.assertFalse(headroom_corner_satisfies_slack(parallel, branches))
        self.assertEqual(headroom_box_profile(choice, branches), choice_residual)
        self.assertNotEqual(headroom_box_profile(parallel, branches), parallel_residual)

    def test_equal_headroom_states_have_divergent_successor_headroom(self) -> None:
        choice = make_state(
            (1,),
            frontiers=downward_closure((("b1",), ("b2",))),
        )
        parallel = make_state(
            (1,),
            frontiers=downward_closure((("b1", "b2"),)),
        )
        first = make_reservation_batch((("b1", (1,)), ("b2", (0,))))
        choice_next = reserve_batch(choice, first, "choice")
        parallel_next = reserve_batch(parallel, first, "parallel")
        self.assertEqual((0,), branch_headroom(choice_next, "b1"))
        self.assertEqual((0,), branch_headroom(parallel_next, "b1"))
        self.assertEqual((1,), branch_headroom(choice_next, "b2"))
        self.assertEqual((0,), branch_headroom(parallel_next, "b2"))

    def test_bounded_residual_derivative_expands_parent_domain(self) -> None:
        branches = ("b1", "b2")
        state = make_state(
            (3,),
            frontiers=downward_closure((("b1",), ("b2",))),
        )
        accepted = make_reservation_batch((("b1", (1,)), ("b2", (0,))))
        successor, derivative, parent_bound = bounded_residual_derivative(
            state, accepted, branches, successor_bound=2
        )
        self.assertEqual(3, parent_bound)
        self.assertEqual(successor, derivative)
        # Exercise the part that would be lost by truncating the parent at 2:
        # x_b1 + y_b1 = 3 for this admitted successor batch.
        y = make_reservation_batch((("b1", (2,)), ("b2", (0,))))
        self.assertIn(y, successor)
        self.assertEqual(
            9,
            len(tuple(enumerate_reservation_batches(branches, 1, 2))),
        )

    def test_knowledge_checker_is_profile_intersection(self) -> None:
        branches = ("b1", "b2")
        choice = make_state(
            (1,),
            frontiers=downward_closure((("b1",), ("b2",))),
        )
        parallel = make_state(
            (1,),
            frontiers=downward_closure((("b1", "b2"),)),
        )
        intersection = knowledge_residual_intersection(
            (choice, parallel), branches, component_bound=1
        )
        self.assertEqual(
            enumerated_residual_profile(parallel, branches, 1), intersection
        )
        for batch in enumerate_reservation_batches(branches, 1, 1):
            self.assertEqual(
                batch in intersection,
                batch_in_residual(choice, batch) and batch_in_residual(parallel, batch),
            )

    def test_prepare_precedes_dispatch_and_retry_reuses_attempt_binding(self) -> None:
        authority = make_state(
            (2,),
            conditional=(
                Claim("first", (1,), "worker"),
                Claim("second", (1,), "worker"),
            ),
            frontiers=downward_closure((("worker",),)),
        )
        initial = make_lifecycle_state(authority)
        with self.assertRaisesRegex(LifecycleRejected, "no live ticket"):
            dispatch_operation(initial, "stable-op")

        prepared = prepare_operations(
            initial,
            (("first", "stable-op", "deduplicated"),),
            "prepare-first",
        )
        self.assertEqual("prepared", prepared.ticket("stable-op").phase)
        self.assertEqual(
            frozenset(("first",)),
            frozenset(claim.claim_id for claim in prepared.authority.durable),
        )
        with self.assertRaisesRegex(LifecycleRejected, "inflight or uncertain"):
            retry_operation(prepared, "stable-op")
        with self.assertRaisesRegex(LifecycleRejected, "attempted work"):
            settle_operation(prepared, "stable-op", "too-early")
        canceled = settle_operation(prepared, "stable-op", "cancelled")
        self.assertEqual((), canceled.tickets)
        self.assertEqual(prepared.authority.durable, canceled.authority.durable)
        self.assertEqual("cancelled", canceled.receipts[0].outcome)

        first_send = dispatch_operation(prepared, "stable-op")
        self.assertEqual(("stable-op", "first"), first_send.abstract_effect)
        self.assertEqual("stable-op", first_send.physical_attempt_id)
        self.assertEqual("inflight", first_send.state.ticket("stable-op").phase)
        with self.assertRaisesRegex(LifecycleRejected, "prepared ticket"):
            dispatch_operation(first_send.state, "stable-op")

        retry = retry_operation(first_send.state, "stable-op")
        self.assertEqual(first_send.state, retry.state)
        self.assertIsNone(retry.abstract_effect)
        self.assertEqual(("stable-op", "first"), retry.attempt)
        self.assertEqual("stable-op", retry.physical_attempt_id)

        settled = settle_operation(retry.state, "stable-op", "committed")
        self.assertEqual((), settled.tickets)
        self.assertEqual("stable-op", settled.receipts[0].operation_id)
        with self.assertRaisesRegex(LifecycleRejected, "no live ticket"):
            retry_operation(settled, "stable-op")
        with self.assertRaisesRegex(LifecycleRejected, "not fresh"):
            prepare_operations(
                settled,
                (("second", "stable-op", "deduplicated"),),
                "reuse-receipt",
            )

    def test_tombstoned_branch_cannot_retain_tentative_claim(self) -> None:
        authority = make_state(
            (1,),
            conditional=(Claim("stale", (1,), "worker"),),
            frontiers=downward_closure((("worker",),)),
        )
        with self.assertRaisesRegex(
            ValueError, "tombstoned branches cannot retain tentative claims"
        ):
            make_lifecycle_state(
                authority,
                tombstoned_branches=("worker",),
            )

        empty_owner_state = make_state(
            (1,),
            conditional=(Claim("live", (1,), "worker"),),
            frontiers=downward_closure((("worker",), ("idle",))),
        )
        cleaned = cleanup_unsupported_owners(
            empty_owner_state,
            downward_closure((("worker",),)),
        )
        self.assertEqual(frozenset(), cleaned.tombstoned_branches)

        historical = make_lifecycle_state(
            make_state(
                (1,),
                frontiers=downward_closure((("old",),)),
            ),
            tombstoned_branches=("dead",),
        )
        with self.assertRaisesRegex(
            LifecycleRejected, "reuse tombstoned branch epochs"
        ):
            restore_replace(historical, "old", "dead")

    def test_crash_recovery_distinguishes_prepared_inflight_and_uncertain(self) -> None:
        authority = make_state(
            (1,),
            conditional=(Claim("effect", (1,), "worker"),),
            frontiers=downward_closure((("worker",),)),
        )
        prepared = prepare_operations(
            make_lifecycle_state(authority),
            (("effect", "stable-op", "aggregate-bounded"),),
            "prepare-effect",
        )
        self.assertEqual(prepared, crash_recover(prepared))

        inflight = dispatch_operation(prepared, "stable-op").state
        uncertain = crash_recover(inflight)
        self.assertEqual("uncertain", uncertain.ticket("stable-op").phase)
        self.assertEqual(uncertain, crash_recover(uncertain))
        retried = retry_operation(uncertain, "stable-op")
        self.assertEqual("inflight", retried.state.ticket("stable-op").phase)
        self.assertEqual(uncertain.authority, retried.state.authority)
        self.assertEqual(uncertain.contract, retried.state.contract)
        self.assertIsNone(retried.abstract_effect)
        self.assertEqual(("stable-op", "effect"), retried.attempt)
        settled = settle_operation(retried.state, "stable-op", "observed")
        self.assertEqual("observed", settled.receipts[0].outcome)
        self.assertEqual(settled, crash_recover(settled))

    def test_revoke_closes_new_authorization_but_sealed_operation_finishes(self) -> None:
        authority = make_state(
            (2,),
            conditional=(
                Claim("sealed", (1,), "worker"),
                Claim("not-sealed", (1,), "worker"),
            ),
            frontiers=downward_closure((("worker",),)),
        )
        with self.assertRaisesRegex(ValueError, "cannot remain in closed epochs"):
            make_lifecycle_state(authority, closed_epochs=("epoch-0",))
        prepared = prepare_operations(
            make_lifecycle_state(authority),
            (("sealed", "stable-op", "deduplicated"),),
            "seal-before-revoke",
        )
        revoked = revoke_epoch(prepared, "epoch-0")
        self.assertEqual(frozenset(("epoch-0",)), revoked.closed_epochs)
        self.assertEqual(
            frozenset(("not-sealed",)), revoked.terminal_claim_ids
        )
        self.assertEqual("prepared", revoked.ticket("stable-op").phase)
        with self.assertRaisesRegex(LifecycleRejected, "not tentative"):
            prepare_operations(
                revoked,
                (("not-sealed", "late-op", "deduplicated"),),
                "prepare-after-revoke",
            )

        sent = dispatch_operation(revoked, "stable-op")
        self.assertEqual(("stable-op", "sealed"), sent.abstract_effect)
        settled = settle_operation(sent.state, "stable-op", "finished-after-revoke")
        self.assertEqual("finished-after-revoke", settled.receipts[0].outcome)
        self.assertEqual(frozenset(("epoch-0",)), settled.closed_epochs)

    def test_replace_live_and_fork_preserve_durable_lifecycle_history(self) -> None:
        authority = make_state(
            (4,),
            conditional=(
                Claim("pending", (1,), "old"),
                Claim("sealed-a", (1,), "old"),
                Claim("sealed-b", (1,), "old"),
                Claim("sealed-c", (1,), "old"),
            ),
            frontiers=downward_closure((("old", "peer"),)),
        )
        sealed = prepare_operations(
            make_lifecycle_state(authority),
            (
                ("sealed-a", "op-a", "deduplicated"),
                ("sealed-b", "op-b", "aggregate-bounded"),
                ("sealed-c", "op-c", "deduplicated"),
            ),
            "structural-seal",
        )
        with_receipt = settle_operation(
            dispatch_operation(sealed, "op-a").state,
            "op-a",
            "done",
        )
        uncertain = crash_recover(
            dispatch_operation(with_receipt, "op-b").state
        )
        self.assertEqual("uncertain", uncertain.ticket("op-b").phase)
        self.assertEqual("prepared", uncertain.ticket("op-c").phase)

        targets = (
            restore_replace(
                uncertain,
                "old",
                "restored",
                (("pending", "restored"),),
            ),
            restore_live(uncertain, "old", "restored"),
            fork_branch(
                uncertain,
                "old",
                "left",
                "right",
                parallel=False,
                transfers=(("pending", "left"),),
            ),
            fork_branch(
                uncertain,
                "old",
                "left",
                "right",
                parallel=True,
                transfers=(("pending", "right"),),
            ),
        )
        for target in targets:
            self.assertTrue(structural_history_preserved(uncertain, target))
            self.assertEqual(uncertain.authority.durable, target.authority.durable)
            self.assertEqual(uncertain.receipts, target.receipts)
            self.assertEqual(uncertain.tickets, target.tickets)
            self.assertEqual("uncertain", target.ticket("op-b").phase)
            self.assertEqual("prepared", target.ticket("op-c").phase)
            self.assertTrue(target.contract.support)

        replace_target, live_target, choice_target, parallel_target = targets
        self.assertIn("old", replace_target.tombstoned_branches)
        self.assertIn("old", choice_target.tombstoned_branches)
        self.assertIn("old", parallel_target.tombstoned_branches)
        self.assertNotIn("old", live_target.tombstoned_branches)
        self.assertEqual(
            ("restored",),
            tuple(claim.branch for claim in replace_target.authority.conditional),
        )
        self.assertEqual(
            ("old",),
            tuple(claim.branch for claim in live_target.authority.conditional),
        )
        restored_only = frozenset(("restored",))
        self.assertIn(restored_only, live_target.contract.support)
        self.assertEqual((3,), live_target.authority.frontier_load(restored_only))

    def test_structural_refinement_rejects_duplicate_claim_transfer(self) -> None:
        authority = make_state(
            (1,),
            conditional=(Claim("pending", (1,), "old"),),
            frontiers=downward_closure((("old",),)),
        )
        lifecycle = make_lifecycle_state(authority)
        canceled = restore_replace(lifecycle, "old", "restored")
        self.assertEqual(frozenset(("pending",)), canceled.terminal_claim_ids)
        self.assertEqual((), canceled.authority.conditional)
        with self.assertRaisesRegex(LifecycleRejected, "at most once"):
            fork_branch(
                lifecycle,
                "old",
                "left",
                "right",
                parallel=True,
                transfers=(("pending", "left"), ("pending", "right")),
            )


if __name__ == "__main__":
    unittest.main()
