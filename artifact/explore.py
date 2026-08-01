"""Deterministic exhaustive checks over small authority-continuity states."""

from __future__ import annotations

import argparse
import json
from functools import lru_cache
from itertools import product
from pathlib import Path
from typing import Iterable, Iterator

from authority_continuity import (
    Claim,
    FrozenThresholdGuard,
    FrontierFamily,
    GuardTerm,
    GuardedContract,
    LifecycleRejected,
    LifecycleState,
    NoTopologyRepair,
    batch_admitted_by_target,
    batch_in_residual,
    bounded_residual_derivative,
    branch_headroom,
    claims_have_owner_support,
    cleanup_unsupported_owners,
    crash_recover,
    dispatch_operation,
    downward_closure,
    enumerate_reservation_batches,
    enumerated_residual_profile,
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


def all_downward_closed_families(branches: tuple[str, ...]) -> Iterator[FrontierFamily]:
    frontiers = tuple(powerset(branches))
    # Every nonempty downward-closed family contains the empty frontier.
    for mask in range(1 << len(frontiers)):
        if not (mask & 1):
            continue
        family = frozenset(
            frontier for index, frontier in enumerate(frontiers) if mask & (1 << index)
        )
        if is_downward_closed(family):
            yield family


@lru_cache(maxsize=None)
def downward_closed_subfamilies(family: FrontierFamily) -> tuple[FrontierFamily, ...]:
    frontiers = tuple(sorted(family, key=lambda item: (len(item), tuple(sorted(item)))))
    result = []
    for mask in range(1, 1 << len(frontiers)):
        candidate = frozenset(
            frontier for index, frontier in enumerate(frontiers) if mask & (1 << index)
        )
        if is_downward_closed(candidate):
            result.append(candidate)
    return tuple(result)


def proper_nonempty_subsets(items: tuple[str, ...]) -> Iterable[tuple[str, ...]]:
    for subset in powerset(items):
        if subset:
            yield tuple(sorted(subset))


def exhaustive_checks() -> dict[str, object]:
    raw_ac_cases = 0
    well_formed_ac_cases = 0
    well_formed_safe_source_states = 0
    maximal_cases = 0
    safe_restrictions = 0
    confluence_cases = 0
    guarded_repair_cases = 0
    guarded_membership_checks = 0
    guarded_confluence_cases = 0
    profile_source_states = 0
    reserve_headroom_cases = 0
    batch_residual_cases = 0
    derivative_cases = 0
    derivative_memberships = 0
    rectangularity_cases = 0
    rectangular_states = 0
    nonrectangular_states = 0

    for branch_count in range(1, 4):
        branches = tuple(f"b{index}" for index in range(branch_count))
        families = tuple(all_downward_closed_families(branches))
        for family in families:
            for weights in product((1, 2), repeat=branch_count):
                conditional = tuple(
                    Claim(f"c{index}", (weights[index],), branch)
                    for index, branch in enumerate(branches)
                )
                for durable_load in (0, 1):
                    durable = (
                        (Claim("durable", (durable_load,), None),)
                        if durable_load
                        else ()
                    )
                    for grant in range(8):
                        state = make_state(
                            (grant,),
                            durable=durable,
                            conditional=conditional,
                            frontiers=family,
                        )
                        # Independent formulations of AC: universal frontier check
                        # and componentwise supremum need.
                        raw_ac_cases += 1
                        assert state.authority_continuous == vector_leq(state.need, state.grant)
                        if not owner_support_well_formed(state):
                            continue
                        well_formed_ac_cases += 1
                        if not state.authority_continuous:
                            continue
                        well_formed_safe_source_states += 1

                        present_branches = frozenset().union(*family)

                        # Residual-profile theorems assume well-formed owner
                        # support.  This explorer gives every syntactic branch
                        # a claim, so profile checks use exactly the families
                        # in which every such owner occurs.
                        if present_branches != frozenset(branches):
                            raise AssertionError("well-formed owner support lost a branch")
                        profile_source_states += 1
                        for branch in branches:
                            for demand in range(3):
                                weight = (demand,)
                                batch = make_reservation_batch(
                                    ((branch, weight),)
                                )
                                by_headroom = reserve_admitted_by_headroom(
                                    state, branch, weight
                                )
                                by_target = batch_admitted_by_target(state, batch)
                                assert by_headroom == by_target
                                reserve_headroom_cases += 1

                        bounded_batches = tuple(
                            enumerate_reservation_batches(branches, 1, 2)
                        )
                        for reservation in bounded_batches:
                            assert batch_in_residual(
                                state, reservation
                            ) == batch_admitted_by_target(state, reservation)
                            batch_residual_cases += 1

                        headroom_box = headroom_box_profile(state, branches)
                        max_headroom_component = max(
                            (
                                component
                                for branch in branches
                                for component in branch_headroom(state, branch) or ()
                            ),
                            default=0,
                        )
                        exact_residual = enumerated_residual_profile(
                            state,
                            branches,
                            max_headroom_component,
                        )
                        is_rectangular = exact_residual == headroom_box
                        corner_satisfies = headroom_corner_satisfies_slack(
                            state, branches
                        )
                        assert is_rectangular == corner_satisfies
                        rectangularity_cases += 1
                        if is_rectangular:
                            rectangular_states += 1
                        else:
                            nonrectangular_states += 1

                        prefix_batches = tuple(
                            enumerate_reservation_batches(branches, 1, 1)
                        )
                        for prefix in prefix_batches:
                            if not batch_in_residual(state, prefix):
                                continue
                            successor_profile, derivative_profile, parent_bound = (
                                bounded_residual_derivative(
                                    state,
                                    prefix,
                                    branches,
                                    successor_bound=2,
                                )
                            )
                            assert parent_bound == 2 + max(
                                (
                                    component
                                    for _, weight in prefix
                                    for component in weight
                                ),
                                default=0,
                            )
                            assert successor_profile == derivative_profile
                            derivative_cases += 1
                            derivative_memberships += len(bounded_batches)

                        for index, branch in enumerate(branches):
                            if branch not in present_branches:
                                continue
                            claim_id = f"c{index}"
                            repaired = state.promote_maximally((claim_id,))
                            maximal_cases += 1
                            assert repaired.authority_continuous
                            assert is_downward_closed(repaired.frontiers)

                            plain_target = state.promote_plain((claim_id,))
                            guarded = install_exact_repair(
                                plain_target,
                                GuardedContract(family),
                                "exhaustive-single",
                            )
                            guarded_repair_cases += 1
                            assert guarded.support == repaired.frontiers
                            assert guarded_authority_continuous(plain_target, guarded)
                            for frontier in family:
                                expected = vector_leq(
                                    plain_target.frontier_load(frontier),
                                    plain_target.grant,
                                )
                                assert guarded.allows(frontier) == expected
                                guarded_membership_checks += 1

                            for restriction in downward_closed_subfamilies(family):
                                candidate = plain_target.with_frontiers(restriction)
                                if candidate.authority_continuous:
                                    safe_restrictions += 1
                                    assert restriction <= repaired.frontiers

                        claim_ids = tuple(f"c{index}" for index in range(branch_count))
                        if branch_count < 2:
                            continue
                        for left in proper_nonempty_subsets(claim_ids):
                            remaining = tuple(item for item in claim_ids if item not in left)
                            for right in proper_nonempty_subsets(remaining):
                                union = tuple(sorted(left + right))
                                try:
                                    batch = state.promote_maximally(union)
                                except NoTopologyRepair:
                                    continue
                                left_then_right = state.promote_maximally(left).promote_maximally(right)
                                right_then_left = state.promote_maximally(right).promote_maximally(left)
                                assert batch == left_then_right == right_then_left
                                confluence_cases += 1

                                base_contract = GuardedContract(family)
                                batch_state, batch_contract = promote_with_exact_guard(
                                    state, base_contract, union, "batch"
                                )
                                left_state, left_contract = promote_with_exact_guard(
                                    state, base_contract, left, "left"
                                )
                                left_right_state, left_right_contract = promote_with_exact_guard(
                                    left_state, left_contract, right, "left-right"
                                )
                                right_state, right_contract = promote_with_exact_guard(
                                    state, base_contract, right, "right"
                                )
                                right_left_state, right_left_contract = promote_with_exact_guard(
                                    right_state, right_contract, left, "right-left"
                                )
                                assert batch_state == left_right_state == right_left_state
                                assert (
                                    batch_contract.support
                                    == left_right_contract.support
                                    == right_left_contract.support
                                    == batch.frontiers
                                )
                                guarded_confluence_cases += 1

    source, escaped, witness = plain_escape_counterexample()
    litmus = snapshot_local_impossibility_litmus()
    assert source.authority_continuous and not escaped.authority_continuous
    assert litmus["replace"]["pre"]["safe"]
    assert litmus["live"]["pre"]["safe"]
    assert litmus["replace"]["successor"]["safe"]
    assert not litmus["live"]["successor"]["safe"]

    # Strict expressiveness: exact promotion produces U_{2,3}, which no
    # pairwise conflict graph (and therefore no cograph) can represent.
    higher_order_base = downward_closure((("b",), ("x", "y", "z")))
    higher_order_source = make_state(
        (3,),
        conditional=(
            Claim("cb", (1,), "b"),
            Claim("cx", (1,), "x"),
            Claim("cy", (1,), "y"),
            Claim("cz", (1,), "z"),
        ),
        frontiers=higher_order_base,
    )
    higher_order_target = higher_order_source.promote_plain(("cb",))
    higher_order_contract = install_exact_repair(
        higher_order_target,
        GuardedContract(higher_order_base),
        "higher-order",
    )
    xyz = ("x", "y", "z")
    u23 = frozenset(frontier for frontier in powerset(xyz) if len(frontier) <= 2)
    guarded_xyz = frozenset(
        frontier
        for frontier in higher_order_contract.support
        if frontier <= frozenset(xyz)
    )
    assert guarded_xyz == u23
    assert not is_conflict_graph_representable(guarded_xyz, xyz)

    # A dynamic/current-Q guard would reopen the forbidden triple after cx is
    # withdrawn.  The durable frozen guard retains its original meaning.
    withdrawn = withdraw_tentative(higher_order_target, "cx")
    dynamic_contract = GuardedContract(
        higher_order_base,
        (exact_repair_guard(withdrawn, "dynamic"),),
    )
    triple = frozenset(xyz)
    assert triple in dynamic_contract.support
    assert triple not in higher_order_contract.support

    # OR-lineage transport charges a live-restored pair once; copying a term to
    # both descendants would charge it twice.
    restore_base = downward_closure((("old",),))
    restore_guard = FrozenThresholdGuard(
        "restore-lineage",
        (2,),
        (GuardTerm("old-lineage", (2,), frozenset(("old",))),),
    )
    transported = GuardedContract(
        restore_base, (restore_guard,)
    ).transport_live_restore("old", "restored")
    restored_pair = frozenset(("old", "restored"))
    naive_guard = FrozenThresholdGuard(
        "naive-restore-copy",
        (2,),
        (
            GuardTerm("naive-old", (2,), frozenset(("old",))),
            GuardTerm("naive-restored", (2,), frozenset(("restored",))),
        ),
    )
    assert transported.guards[0].charge(restored_pair) == (2,)
    assert naive_guard.charge(restored_pair) == (4,)

    # When every promoted claim's original owner survives in the final support,
    # exact repair agrees denotationally for the atomic batch and both serial
    # orders.  Guard syntax is intentionally not compared.
    exclusive_base = downward_closure((("a",), ("b",)))
    exclusive_source = make_state(
        (2,),
        conditional=(
            Claim("ca", (1,), "a"),
            Claim("cb", (1,), "b"),
        ),
        frontiers=exclusive_base,
    )
    exact_batch_state, exact_batch_contract = promote_with_exact_guard(
        exclusive_source,
        GuardedContract(exclusive_base),
        ("ca", "cb"),
        "exclusive-batch",
    )
    exact_a_state, exact_a_contract = promote_with_exact_guard(
        exclusive_source,
        GuardedContract(exclusive_base),
        ("ca",),
        "exclusive-a",
    )
    exact_serial_state, exact_serial_contract = promote_with_exact_guard(
        exact_a_state,
        exact_a_contract,
        ("cb",),
        "exclusive-a-b",
    )
    exact_b_state, exact_b_contract = promote_with_exact_guard(
        exclusive_source,
        GuardedContract(exclusive_base),
        ("cb",),
        "exclusive-b",
    )
    exact_reverse_state, exact_reverse_contract = promote_with_exact_guard(
        exact_b_state,
        exact_b_contract,
        ("ca",),
        "exclusive-b-a",
    )
    positive_final_owner_support = claims_have_owner_support(
        exclusive_source,
        ("ca", "cb"),
        exact_batch_contract.support,
    )
    positive_denotational_confluence = (
        exact_batch_state == exact_serial_state == exact_reverse_state
        and exact_batch_contract.support
        == exact_serial_contract.support
        == exact_reverse_contract.support
    )
    assert positive_final_owner_support
    assert positive_denotational_confluence

    # The witnessed condition-on-owner shortcut remains a counterexample to
    # confusing abstract confluence with operational serializability.
    witnessed = witnessed_promote_with_tombstones(exclusive_source, "ca")
    assert witnessed.tombstoned_branches == frozenset(("b",))
    assert witnessed.terminal_claim_ids == frozenset(("cb",))
    second_escape_enabled = any(
        claim.claim_id == "cb" for claim in witnessed.state.conditional
    )
    assert not second_escape_enabled

    # If final-owner support fails, exact repair plus mandatory cleanup can
    # make one serial order disable the other step.  The enabled order still
    # reaches the same cleaned state and denotational support as the atomic
    # batch, so this is a sharp boundary rather than a guard-syntax artifact.
    absent_base = downward_closure((("s",), ("t",)))
    absent_source = make_state(
        (2,),
        conditional=(
            Claim("cs", (1,), "s"),
            Claim("ct", (1,), "t"),
            Claim("u", (1,), "t"),
        ),
        frontiers=absent_base,
    )
    absent_contract = GuardedContract(absent_base)
    absent_atomic_state, absent_atomic_contract = promote_with_exact_guard(
        absent_source,
        absent_contract,
        ("cs", "ct"),
        "absent-atomic",
    )
    absent_final_owner_support = claims_have_owner_support(
        absent_source,
        ("cs", "ct"),
        absent_atomic_contract.support,
    )
    assert not absent_final_owner_support
    absent_atomic_cleanup = cleanup_unsupported_owners(
        absent_atomic_state,
        absent_atomic_contract.support,
    )
    assert absent_atomic_cleanup.tombstoned_branches == frozenset(("t",))
    assert absent_atomic_cleanup.terminal_claim_ids == frozenset(("u",))

    absent_s_state, absent_s_contract = promote_with_exact_guard(
        absent_source,
        absent_contract,
        ("cs",),
        "absent-s-first",
    )
    absent_s_cleanup = cleanup_unsupported_owners(
        absent_s_state,
        absent_s_contract.support,
    )
    assert absent_s_cleanup.terminal_claim_ids == frozenset(("ct", "u"))
    absent_s_second_enabled = any(
        claim.claim_id == "ct" for claim in absent_s_cleanup.state.conditional
    )
    assert not absent_s_second_enabled

    absent_t_state, absent_t_contract = promote_with_exact_guard(
        absent_source,
        absent_contract,
        ("ct",),
        "absent-t-first",
    )
    absent_t_second_enabled = any(
        claim.claim_id == "cs" for claim in absent_t_state.conditional
    )
    assert absent_t_second_enabled
    assert owner_support_well_formed(absent_t_state, absent_t_contract.support)
    absent_serial_state, absent_serial_contract = promote_with_exact_guard(
        absent_t_state,
        absent_t_contract,
        ("cs",),
        "absent-t-s",
    )
    absent_serial_cleanup = cleanup_unsupported_owners(
        absent_serial_state,
        absent_serial_contract.support,
    )
    absent_enabled_order_matches_atomic = (
        absent_serial_contract.support == absent_atomic_contract.support
        and absent_serial_cleanup.state == absent_atomic_cleanup.state
    )
    assert absent_enabled_order_matches_atomic

    # The fully abstract one-step headroom summary is not update-closed.
    profile_branches = ("b1", "b2")
    choice_profile_state = make_state(
        (1,),
        frontiers=downward_closure((("b1",), ("b2",))),
    )
    parallel_profile_state = make_state(
        (1,),
        frontiers=downward_closure((("b1", "b2"),)),
    )
    choice_headroom = {
        branch: branch_headroom(choice_profile_state, branch)
        for branch in profile_branches
    }
    parallel_headroom = {
        branch: branch_headroom(parallel_profile_state, branch)
        for branch in profile_branches
    }
    assert choice_headroom == parallel_headroom == {"b1": (1,), "b2": (1,)}
    reserve_b1 = make_reservation_batch((("b1", (1,)), ("b2", (0,))))
    choice_successor = reserve_batch(choice_profile_state, reserve_b1, "choice-profile")
    parallel_successor = reserve_batch(
        parallel_profile_state, reserve_b1, "parallel-profile"
    )
    choice_successor_headroom = {
        branch: branch_headroom(choice_successor, branch)
        for branch in profile_branches
    }
    parallel_successor_headroom = {
        branch: branch_headroom(parallel_successor, branch)
        for branch in profile_branches
    }
    assert choice_successor_headroom == {"b1": (0,), "b2": (1,)}
    assert parallel_successor_headroom == {"b1": (0,), "b2": (0,)}

    choice_residual = enumerated_residual_profile(
        choice_profile_state, profile_branches, 1
    )
    parallel_residual = enumerated_residual_profile(
        parallel_profile_state, profile_branches, 1
    )
    both_units = make_reservation_batch((("b1", (1,)), ("b2", (1,))))
    assert both_units in choice_residual and both_units not in parallel_residual
    fixed_choice_rectangular = (
        choice_residual == headroom_box_profile(choice_profile_state, profile_branches)
        and headroom_corner_satisfies_slack(
            choice_profile_state, profile_branches
        )
    )
    fixed_parallel_rectangular = (
        parallel_residual
        == headroom_box_profile(parallel_profile_state, profile_branches)
    )
    assert fixed_choice_rectangular
    assert not fixed_parallel_rectangular
    assert not headroom_corner_satisfies_slack(
        parallel_profile_state, profile_branches
    )

    # For the indistinguishable two-state knowledge set, the greatest sound
    # bounded checker is exactly the residual-profile intersection.
    knowledge_bound = 2
    knowledge_profile = knowledge_residual_intersection(
        (choice_profile_state, parallel_profile_state),
        profile_branches,
        knowledge_bound,
    )
    knowledge_decisions = 0
    for reservation in enumerate_reservation_batches(
        profile_branches, 1, knowledge_bound
    ):
        assert (reservation in knowledge_profile) == (
            batch_in_residual(choice_profile_state, reservation)
            and batch_in_residual(parallel_profile_state, reservation)
        )
        knowledge_decisions += 1

    # Explore the finite recovery graph around one sealed operation.  The
    # second tentative claim makes Revoke's terminal cleanup observable while
    # the first claim remains durable behind its ticket.
    lifecycle_authority = make_state(
        (2,),
        conditional=(
            Claim("sealed", (1,), "worker"),
            Claim("unsealed", (1,), "worker"),
        ),
        frontiers=downward_closure((("worker",),)),
    )
    lifecycle_initial = make_lifecycle_state(lifecycle_authority)
    tombstoned_branch_retention_rejected = False
    try:
        make_lifecycle_state(
            lifecycle_authority,
            tombstoned_branches=("worker",),
        )
    except ValueError:
        tombstoned_branch_retention_rejected = True
    assert tombstoned_branch_retention_rejected
    historical_branch = make_lifecycle_state(
        make_state(
            (1,),
            frontiers=downward_closure((("old",),)),
        ),
        tombstoned_branches=("dead",),
    )
    tombstoned_branch_reopen_rejected = False
    try:
        restore_replace(historical_branch, "old", "dead")
    except LifecycleRejected:
        tombstoned_branch_reopen_rejected = True
    assert tombstoned_branch_reopen_rejected
    dispatch_before_prepare_rejected = False
    try:
        dispatch_operation(lifecycle_initial, "stable-op")
    except LifecycleRejected:
        dispatch_before_prepare_rejected = True
    assert dispatch_before_prepare_rejected
    lifecycle_prepared = prepare_operations(
        lifecycle_initial,
        (("sealed", "stable-op", "deduplicated"),),
        "lifecycle-prepare",
    )
    assert crash_recover(lifecycle_prepared) == lifecycle_prepared

    first_dispatch = dispatch_operation(lifecycle_prepared, "stable-op")
    assert first_dispatch.abstract_effect == ("stable-op", "sealed")
    lifecycle_uncertain = crash_recover(first_dispatch.state)
    assert lifecycle_uncertain.ticket("stable-op").phase == "uncertain"
    lifecycle_retry = retry_operation(lifecycle_uncertain, "stable-op")
    assert lifecycle_retry.state.ticket("stable-op").phase == "inflight"
    assert lifecycle_retry.state.authority == lifecycle_uncertain.authority
    assert lifecycle_retry.state.contract == lifecycle_uncertain.contract
    assert lifecycle_retry.abstract_effect is None
    assert lifecycle_retry.attempt == ("stable-op", "sealed")
    assert lifecycle_retry.physical_attempt_id == "stable-op"
    lifecycle_settled = settle_operation(
        lifecycle_retry.state,
        "stable-op",
        "observed",
    )
    assert not lifecycle_settled.tickets
    assert lifecycle_settled.receipts[0].operation_id == "stable-op"
    lifecycle_canceled = settle_operation(
        lifecycle_prepared,
        "stable-op",
        "cancelled",
    )
    assert not lifecycle_canceled.tickets
    assert lifecycle_canceled.authority.durable == lifecycle_prepared.authority.durable

    lifecycle_revoked_prepared = revoke_epoch(
        lifecycle_prepared,
        "epoch-0",
    )
    assert lifecycle_revoked_prepared.terminal_claim_ids == frozenset(("unsealed",))
    revoked_dispatch = dispatch_operation(
        lifecycle_revoked_prepared,
        "stable-op",
    )
    assert revoked_dispatch.abstract_effect == ("stable-op", "sealed")

    def lifecycle_phase(current: LifecycleState) -> str:
        if current.receipts:
            return "settled"
        return current.ticket("stable-op").phase

    recovery_states = {lifecycle_prepared}
    recovery_queue = [lifecycle_prepared]
    recovery_edges = 0
    action_edge_counts = {
        "crash": 0,
        "dispatch": 0,
        "retry": 0,
        "settle": 0,
        "revoke": 0,
    }
    while recovery_queue:
        current = recovery_queue.pop(0)
        for action in action_edge_counts:
            try:
                if action == "crash":
                    successor = crash_recover(current)
                elif action == "dispatch":
                    successor = dispatch_operation(current, "stable-op").state
                elif action == "retry":
                    successor = retry_operation(current, "stable-op").state
                elif action == "settle":
                    successor = settle_operation(
                        current,
                        "stable-op",
                        "observed",
                    )
                else:
                    successor = revoke_epoch(current, "epoch-0")
            except LifecycleRejected:
                continue
            recovery_edges += 1
            action_edge_counts[action] += 1
            if successor not in recovery_states:
                recovery_states.add(successor)
                recovery_queue.append(successor)
    recovered_phase_epoch_pairs = {
        (lifecycle_phase(state), bool(state.closed_epochs))
        for state in recovery_states
    }
    assert recovered_phase_epoch_pairs == {
        (phase, closed)
        for phase in ("prepared", "inflight", "uncertain", "settled")
        for closed in (False, True)
    }
    assert len(recovery_states) == 8
    assert recovery_edges == 22
    assert action_edge_counts == {
        "crash": 8,
        "dispatch": 2,
        "retry": 4,
        "settle": 4,
        "revoke": 4,
    }

    # Exercise structural certificates with a receipt plus prepared and
    # uncertain tickets live.  Each helper checks every target frontier against
    # the source projection, while the assertions below check history retention.
    structural_authority = make_state(
        (4,),
        conditional=(
            Claim("pending", (1,), "old"),
            Claim("sealed-a", (1,), "old"),
            Claim("sealed-b", (1,), "old"),
            Claim("sealed-c", (1,), "old"),
        ),
        frontiers=downward_closure((("old", "peer"),)),
    )
    structural_sealed = prepare_operations(
        make_lifecycle_state(structural_authority),
        (
            ("sealed-a", "op-a", "deduplicated"),
            ("sealed-b", "op-b", "aggregate-bounded"),
            ("sealed-c", "op-c", "deduplicated"),
        ),
        "structural-prepare",
    )
    structural_receipt = settle_operation(
        dispatch_operation(structural_sealed, "op-a").state,
        "op-a",
        "done",
    )
    structural_source = crash_recover(
        dispatch_operation(structural_receipt, "op-b").state
    )
    structural_targets = {
        "restore_replace": restore_replace(
            structural_source,
            "old",
            "restored",
            (("pending", "restored"),),
        ),
        "restore_live": restore_live(
            structural_source,
            "old",
            "restored",
        ),
        "fork_choice": fork_branch(
            structural_source,
            "old",
            "left",
            "right",
            parallel=False,
            transfers=(("pending", "left"),),
        ),
        "fork_parallel": fork_branch(
            structural_source,
            "old",
            "left",
            "right",
            parallel=True,
            transfers=(("pending", "right"),),
        ),
    }
    for structural_target in structural_targets.values():
        assert structural_history_preserved(
            structural_source,
            structural_target,
        )
        assert structural_target.ticket("op-b").phase == "uncertain"
        assert structural_target.ticket("op-c").phase == "prepared"
        assert structural_target.receipts == structural_source.receipts
    structural_frontier_checks = sum(
        len(target.contract.base_frontiers)
        for target in structural_targets.values()
    )
    assert structural_frontier_checks == 26

    assert profile_source_states == well_formed_safe_source_states
    assert rectangularity_cases == well_formed_safe_source_states
    assert rectangular_states + nonrectangular_states == rectangularity_cases

    return {
        "schema_version": 5,
        "artifact_kind": "finite executable validation (not mechanized proof)",
        "parameters": {
            "authority_coordinates": 1,
            "branches": [1, 2, 3],
            "claim_weights": [1, 2],
            "durable_loads": [0, 1],
            "grants": list(range(8)),
            "frontier_families": "all nonempty downward-closed families",
            "residual_batch_component_bound": 2,
            "derivative_prefix_component_bound": 1,
            "derivative_successor_component_bound": 2,
            "derivative_parent_bound": "2 + max(prefix component), hence at most 3",
            "headline_source_state_filter": (
                "every conditional claim owner occurs in at least one admitted frontier"
            ),
        },
        "checks": {
            "raw_ac_algebra_including_unsupported_owners": {
                "states": raw_ac_cases,
                "headline_evidence": False,
                "purpose": "transcription diagnostic only",
                "status": "pass",
            },
            "ac_need_equivalence": {
                "well_formed_states": well_formed_ac_cases,
                "status": "pass",
            },
            "reserve_headroom_equivalence": {
                "well_formed_safe_source_states": profile_source_states,
                "single_branch_demands_checked": reserve_headroom_cases,
                "demand_components": [0, 1, 2],
                "status": "pass",
            },
            "batch_residual_equivalence": {
                "batch_memberships_checked": batch_residual_cases,
                "component_box": [0, 2],
                "status": "pass",
            },
            "bounded_residual_derivative": {
                "accepted_prefixes_checked": derivative_cases,
                "successor_memberships_compared": derivative_memberships,
                "successor_component_box": [0, 2],
                "parent_component_bound_rule": "2 + max(prefix component)",
                "maximum_parent_component_bound": 3,
                "status": "pass",
            },
            "headroom_not_update_closed": {
                "initial_choice_headroom": {
                    branch: list(value) for branch, value in choice_headroom.items()
                },
                "initial_parallel_headroom": {
                    branch: list(value) for branch, value in parallel_headroom.items()
                },
                "both_unit_batch_in_choice_residual": both_units in choice_residual,
                "both_unit_batch_in_parallel_residual": (
                    both_units in parallel_residual
                ),
                "choice_successor_headroom": {
                    branch: list(value)
                    for branch, value in choice_successor_headroom.items()
                },
                "parallel_successor_headroom": {
                    branch: list(value)
                    for branch, value in parallel_successor_headroom.items()
                },
                "status": "pass",
            },
            "headroom_box_rectangularity": {
                "well_formed_safe_source_states": rectangularity_cases,
                "rectangular_states": rectangular_states,
                "nonrectangular_states": nonrectangular_states,
                "criterion": (
                    "the all-headrooms corner satisfies every frontier slack inequality"
                ),
                "enumeration_bound": (
                    "maximum headroom component in each source; this contains Box(H)"
                ),
                "fixed_choice_rectangular": fixed_choice_rectangular,
                "fixed_parallel_rectangular": fixed_parallel_rectangular,
                "status": "pass",
            },
            "knowledge_profile_intersection": {
                "knowledge_states": 2,
                "bounded_batch_decisions_checked": knowledge_decisions,
                "component_box": [0, knowledge_bound],
                "intersection_profile_size": len(knowledge_profile),
                "status": "pass",
            },
            "lifecycle_recovery_graph": {
                "unique_phase_epoch_states": len(recovery_states),
                "valid_state_action_edges": recovery_edges,
                "edge_counts": action_edge_counts,
                "dispatch_before_prepare_rejected": (
                    dispatch_before_prepare_rejected
                ),
                "tombstoned_branch_retention_rejected": (
                    tombstoned_branch_retention_rejected
                ),
                "tombstoned_branch_reopen_rejected": (
                    tombstoned_branch_reopen_rejected
                ),
                "prepared_survives_crash": (
                    crash_recover(lifecycle_prepared) == lifecycle_prepared
                ),
                "inflight_recovers_uncertain": (
                    lifecycle_uncertain.ticket("stable-op").phase == "uncertain"
                ),
                "retry_reuses_stable_id": (
                    lifecycle_retry.physical_attempt_id == "stable-op"
                ),
                "retry_allocates_no_new_logical_effect": (
                    lifecycle_retry.abstract_effect is None
                ),
                "retry_attempt_reuses_claim_binding": (
                    lifecycle_retry.attempt == ("stable-op", "sealed")
                ),
                "retry_preserves_authority_accounting": (
                    lifecycle_retry.state.authority == lifecycle_uncertain.authority
                    and lifecycle_retry.state.contract == lifecycle_uncertain.contract
                ),
                "retry_returns_inflight": (
                    lifecycle_retry.state.ticket("stable-op").phase == "inflight"
                ),
                "prepared_cancel_retains_durable_claim": (
                    not lifecycle_canceled.tickets
                    and lifecycle_canceled.authority.durable
                    == lifecycle_prepared.authority.durable
                ),
                "settled_ticket_count": len(lifecycle_settled.tickets),
                "settled_receipt_count": len(lifecycle_settled.receipts),
                "status": "pass",
            },
            "revoke_sealed_completion": {
                "closed_epoch": "epoch-0",
                "terminalized_unsealed_claims": sorted(
                    lifecycle_revoked_prepared.terminal_claim_ids
                ),
                "prepared_ticket_retained": (
                    lifecycle_revoked_prepared.ticket("stable-op").phase
                    == "prepared"
                ),
                "sealed_dispatch_after_revoke": (
                    revoked_dispatch.abstract_effect == ("stable-op", "sealed")
                ),
                "status": "pass",
            },
            "structural_lifecycle_preservation": {
                "modes": sorted(structural_targets),
                "target_frontier_simulations_checked": (
                    structural_frontier_checks
                ),
                "source_ticket_phases": sorted(
                    ticket.phase for ticket in structural_source.tickets
                ),
                "source_receipts": len(structural_source.receipts),
                "all_preserve_history": all(
                    structural_history_preserved(
                        structural_source,
                        target,
                    )
                    for target in structural_targets.values()
                ),
                "status": "pass",
            },
            "single_claim_maximal_support": {
                "safe_source_owner_cases": maximal_cases,
                "safe_downward_restrictions_checked": safe_restrictions,
                "status": "pass",
            },
            "exact_frozen_guard_support": {
                "repair_instances": guarded_repair_cases,
                "frontier_memberships_checked": guarded_membership_checks,
                "status": "pass",
            },
            "batched_promotion_confluence": {
                "ordered_disjoint_batches": confluence_cases,
                "guarded_ordered_disjoint_batches": guarded_confluence_cases,
                "status": "pass",
            },
            "higher_order_support": {
                "base_contract": "b choice (x parallel y parallel z)",
                "post_promotion_xyz_support": [
                    sorted(frontier)
                    for frontier in sorted(
                        guarded_xyz,
                        key=lambda item: (len(item), tuple(sorted(item))),
                    )
                ],
                "all_pairs_allowed": all(
                    frozenset(pair) in guarded_xyz
                    for pair in (("x", "y"), ("x", "z"), ("y", "z"))
                ),
                "triple_allowed": triple in guarded_xyz,
                "conflict_graph_representable": is_conflict_graph_representable(
                    guarded_xyz, xyz
                ),
                "guard_residual": list(higher_order_contract.guards[0].residual),
                "status": "pass",
            },
            "frozen_vs_dynamic_guard": {
                "triple_allowed_by_frozen_guard_after_withdraw": (
                    triple in higher_order_contract.support
                ),
                "triple_allowed_by_recomputed_current_q_guard_after_withdraw": (
                    triple in dynamic_contract.support
                ),
                "status": "pass",
            },
            "lineage_or_live_restore": {
                "retained_pair": sorted(restored_pair),
                "or_lineage_charge": list(
                    transported.guards[0].charge(restored_pair)
                ),
                "naively_copied_charge": list(naive_guard.charge(restored_pair)),
                "or_lineage_allows_pair": transported.allows(restored_pair),
                "naive_copy_allows_pair": naive_guard.allows(restored_pair),
                "status": "pass",
            },
            "operational_serialization_boundary": {
                "first_witnessed_owner": "a",
                "tombstoned_next_owner": sorted(witnessed.tombstoned_branches),
                "terminal_next_claims": sorted(witnessed.terminal_claim_ids),
                "second_escape_enabled": second_escape_enabled,
                "status": "pass",
            },
            "final_owner_support_serialization": {
                "positive_final_owner_support": positive_final_owner_support,
                "positive_atomic_equals_both_orders_denotationally": (
                    positive_denotational_confluence
                ),
                "absent_final_owner_support": absent_final_owner_support,
                "absent_s_first_second_enabled": absent_s_second_enabled,
                "absent_t_first_second_enabled": absent_t_second_enabled,
                "enabled_order_matches_atomic_denotationally_after_cleanup": (
                    absent_enabled_order_matches_atomic
                ),
                "status": "pass",
            },
            "snapshot_local_impossibility": {"status": "pass", **litmus},
            "plain_escape_counterexample": {
                "status": "pass",
                "source_safe": source.authority_continuous,
                "target_safe": escaped.authority_continuous,
                "grant": list(escaped.grant),
                "violating_frontier": sorted(witness),
                "violating_load": list(escaped.frontier_load(witness)),
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        help="also write the deterministic JSON result to this path",
    )
    args = parser.parse_args()
    result = exhaustive_checks()
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    print(encoded, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
