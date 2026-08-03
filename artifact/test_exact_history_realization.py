"""Bounded litmus tests for the Exact Agent History Realization contract."""

from __future__ import annotations

from dataclasses import fields, replace
from itertools import permutations
import unittest

from exact_history_realization import (
    ClosedGeneration,
    Contract,
    ForkChoice,
    ForkParallel,
    FrontierGroup,
    GateInvocation,
    HistoryState,
    LiveBranch,
    MergeJoin,
    MergeSelect,
    ModelError,
    NamedContract,
    Occurrence,
    Pomset,
    PrefixPolicy,
    RestoreLive,
    RestoreReplace,
    StaleCut,
    auth,
    check_admission,
    choice,
    commit_gate,
    compile_cut,
    derive_rewrite,
    install_cut,
    linearizations,
    logical_frontier_digest,
    resolve,
    singleton_contract,
)


def permissive_policy(*cells: str) -> PrefixPolicy:
    """All no-repeat traces through the named finite cell universe."""

    allowed = {()}
    for length in range(1, len(cells) + 1):
        allowed.update(permutations(cells, length))
    return PrefixPolicy(frozenset(allowed))


def one(name: str, cell: str) -> Contract:
    return singleton_contract(Occurrence(name, cell))


def base_state(
    *,
    receipts: tuple[str, ...] = (),
    source_cell: str = "current-cell",
) -> HistoryState:
    return HistoryState(
        branches=(LiveBranch("b", one("current", source_cell), "gen:old"),),
        checkpoints=(NamedContract("k", one("saved", "checkpoint-cell")),),
        leaf_registry=(
            NamedContract("L", one("left", "left-cell")),
            NamedContract("R", one("right", "right-cell")),
            NamedContract("J", one("join", "join-cell")),
        ),
        receipts=receipts,
        policy=permissive_policy(
            "current-cell",
            "checkpoint-cell",
            "left-cell",
            "right-cell",
            "join-cell",
        ),
        policy_version=7,
        view_version=10,
    )


def merge_state(mode: str) -> HistoryState:
    return HistoryState(
        branches=(
            LiveBranch("left", one("left-rem", "left-cell"), "gen:left"),
            LiveBranch("right", one("right-rem", "right-cell"), "gen:right"),
        ),
        groups=(FrontierGroup("g", mode, ("left", "right")),),
        leaf_registry=(NamedContract("J", one("join", "join-cell")),),
        policy=permissive_policy("left-cell", "right-cell", "join-cell"),
        policy_version=2,
        view_version=4,
    )


class ResolutionAndAdmissionTests(unittest.TestCase):
    def test_contract_rejects_unobservable_early_completion(self) -> None:
        with self.assertRaisesRegex(ModelError, "termination is observable"):
            Contract(
                (
                    Pomset(()),
                    Pomset((Occurrence("continue", "continue-cell"),)),
                )
            )

    def test_alias_resolution_is_length_preserving(self) -> None:
        pomset = Pomset(
            (
                Occurrence("copy-a", "shared-cell"),
                Occurrence("copy-b", "shared-cell"),
            )
        )
        raw_orders = linearizations(pomset)
        self.assertEqual(2, len(raw_orders))
        for raw in raw_orders:
            trace = resolve(pomset, raw, ())
            self.assertEqual(len(raw), len(trace))
            self.assertEqual(["fresh", "alias"], [event.kind for event in trace])
            self.assertEqual(("shared-cell",), auth(trace))
            self.assertEqual(set(raw), {event.logical_id for event in trace})

        already_receipted = resolve(pomset, raw_orders[0], ("shared-cell",))
        self.assertEqual(["alias", "alias"], [event.kind for event in already_receipted])
        self.assertEqual((), auth(already_receipted))

    def test_alias_pomset_is_admitted_without_erasing_occurrences(self) -> None:
        contract = singleton_contract(
            Occurrence("copy-a", "shared-cell"),
            Occurrence("copy-b", "shared-cell"),
        )
        state = HistoryState(
            branches=(LiveBranch("b", contract, "gen:old"),),
            policy=PrefixPolicy.from_maximal(("shared-cell",)),
        )
        result = check_admission(state, contract)
        self.assertTrue(result.admitted)
        self.assertEqual(2, len(result.safe_completions))
        self.assertTrue(all(len(trace) == 2 for trace in result.safe_completions))
        self.assertTrue(
            all(
                [event.kind for event in trace].count("alias") == 1
                for trace in result.safe_completions
            )
        )

    def test_every_derived_outcome_needs_a_safe_linearization(self) -> None:
        left = one("left", "a")
        right = one("right", "b")
        contract = choice(left, right)
        rejecting = HistoryState(
            branches=(LiveBranch("b", one("current", "c"), "gen:old"),),
            policy=PrefixPolicy.from_maximal(("a",)),
        )
        result = check_admission(rejecting, contract)
        self.assertFalse(result.admitted)
        self.assertIsNotNone(result.impossibility_witness)
        self.assertEqual(1, len(result.safe_completions))

        accepting = HistoryState(
            branches=(LiveBranch("b", one("current", "c"), "gen:old"),),
            policy=PrefixPolicy.from_maximal(("a",), ("b",)),
        )
        admitted = check_admission(accepting, contract)
        self.assertTrue(admitted.admitted)
        self.assertEqual(2, len(admitted.outcomes))
        self.assertTrue(all(outcome.safe for outcome in admitted.outcomes))

    def test_w_is_exactly_prefixes_of_safe_completions(self) -> None:
        contract = singleton_contract(
            Occurrence("a", "a"),
            Occurrence("b", "b"),
        )
        state = HistoryState(
            branches=(LiveBranch("b", contract, "gen:old"),),
            policy=PrefixPolicy.from_maximal(("a", "b"), ("b", "a")),
        )
        result = check_admission(state, contract)
        expected = {()}
        for completion in result.safe_completions:
            expected.update(
                completion[:length] for length in range(len(completion) + 1)
            )
        self.assertEqual(expected, set(result.language_w))
        for prefix in result.language_w:
            self.assertTrue(
                any(
                    completion[: len(prefix)] == prefix
                    for completion in result.safe_completions
                )
            )


class TrustedHistoryDerivationTests(unittest.TestCase):
    def test_operations_have_no_caller_supplied_semantic_fields(self) -> None:
        forbidden = {
            "contract",
            "outcomes",
            "plan",
            "sources",
            "anchors",
            "receipts",
            "receipt_frontier",
        }
        for operation_type in (
            ForkChoice,
            ForkParallel,
            RestoreReplace,
            RestoreLive,
            MergeSelect,
            MergeJoin,
        ):
            self.assertFalse(forbidden & {field.name for field in fields(operation_type)})

    def test_fork_choice_derives_tagged_alternatives_and_source(self) -> None:
        rewrite = derive_rewrite(base_state(), ForkChoice("b", "L", "R"))
        self.assertEqual(("gen:old",), rewrite.sources)
        self.assertEqual(2, len(rewrite.contract.outcomes))
        self.assertEqual("choice", rewrite.next_state.groups[0].mode)
        ids = {
            node.logical_id
            for outcome in rewrite.contract.outcomes
            for node in outcome.nodes
        }
        self.assertEqual(2, len(ids))
        self.assertTrue(all("ForkChoice" in logical_id for logical_id in ids))

    def test_fork_parallel_derives_causal_product(self) -> None:
        rewrite = derive_rewrite(base_state(), ForkParallel("b", "L", "R"))
        self.assertEqual(("gen:old",), rewrite.sources)
        self.assertEqual(1, len(rewrite.contract.outcomes))
        outcome = rewrite.contract.outcomes[0]
        self.assertEqual(2, len(outcome.nodes))
        self.assertEqual(frozenset(), outcome.order)
        self.assertEqual(2, len(linearizations(outcome)))
        self.assertEqual("parallel", rewrite.next_state.groups[0].mode)

    def test_restore_replace_clones_logical_identity_but_retains_cell(self) -> None:
        rewrite = derive_rewrite(base_state(), RestoreReplace("b", "k"))
        self.assertEqual(("gen:old",), rewrite.sources)
        node = rewrite.contract.outcomes[0].nodes[0]
        self.assertNotEqual("saved", node.logical_id)
        self.assertIn("RestoreReplace", node.logical_id)
        self.assertEqual("checkpoint-cell", node.cell)

    def test_restore_live_carries_current_and_clones_checkpoint(self) -> None:
        rewrite = derive_rewrite(base_state(), RestoreLive("b", "k"))
        self.assertEqual(("gen:old",), rewrite.sources)
        outcome = rewrite.contract.outcomes[0]
        by_cell = {node.cell: node.logical_id for node in outcome.nodes}
        self.assertEqual("current", by_cell["current-cell"])
        self.assertNotEqual("saved", by_cell["checkpoint-cell"])
        self.assertEqual("parallel", rewrite.next_state.groups[0].mode)

    def test_merge_select_derives_all_group_sources_and_orders_join(self) -> None:
        rewrite = derive_rewrite(
            merge_state("choice"), MergeSelect("g", "left", "J")
        )
        self.assertEqual(("gen:left", "gen:right"), rewrite.sources)
        outcome = rewrite.contract.outcomes[0]
        ids = {node.logical_id for node in outcome.nodes}
        self.assertIn("left-rem", ids)
        self.assertNotIn("right-rem", ids)
        join = next(logical_id for logical_id in ids if logical_id != "left-rem")
        self.assertIn(("left-rem", join), outcome.order)

    def test_merge_join_derives_all_sources_and_full_predecessor_cut(self) -> None:
        state = merge_state("parallel")
        rewrite = derive_rewrite(state, MergeJoin("g", "J"))
        self.assertEqual(("gen:left", "gen:right"), rewrite.sources)
        outcome = rewrite.contract.outcomes[0]
        join = next(
            node.logical_id for node in outcome.nodes if node.cell == "join-cell"
        )
        self.assertIn(("left-rem", join), outcome.order)
        self.assertIn(("right-rem", join), outcome.order)
        self.assertNotIn(("left-rem", "right-rem"), outcome.order)
        self.assertNotIn(("right-rem", "left-rem"), outcome.order)

        compiled = compile_cut(state, MergeJoin("g", "J"))
        installed = install_cut(state, compiled)
        self.assertEqual(
            frozenset({"gen:left", "gen:right"}), installed.closed_owners
        )
        self.assertEqual(1, len(installed.branches))
        self.assertNotIn(installed.branches[0].owner, installed.closed_owners)

    def test_exact_gate_occurrence_cannot_borrow_an_enabled_cell(self) -> None:
        contract = Contract(
            (
                Pomset(
                    (
                        Occurrence("first", "shared-cell"),
                        Occurrence("second", "shared-cell"),
                    ),
                    frozenset({("first", "second")}),
                ),
            )
        )
        state = HistoryState(
            branches=(LiveBranch("b", contract, "gen:old"),),
            policy=PrefixPolicy.from_maximal(("shared-cell",)),
        )
        with self.assertRaises(ModelError):
            commit_gate(
                state,
                GateInvocation("gen:old", "second", "shared-cell"),
            )
        with self.assertRaises(ModelError):
            commit_gate(
                state,
                GateInvocation("gen:old", "forged", "shared-cell"),
            )

    def test_alias_progress_resolves_choice_without_new_receipt(self) -> None:
        state = HistoryState(
            branches=(
                LiveBranch("left", one("left-call", "shared-cell"), "gen:left"),
                LiveBranch("right", one("right-call", "other-cell"), "gen:right"),
            ),
            groups=(FrontierGroup("g", "choice", ("left", "right")),),
            leaf_registry=(NamedContract("J", one("join", "join-cell")),),
            receipts=("shared-cell",),
            policy=permissive_policy("shared-cell", "other-cell", "join-cell"),
        )
        progressed, event = commit_gate(
            state,
            GateInvocation("gen:left", "left-call", "shared-cell"),
        )
        self.assertEqual("alias", event.kind)
        self.assertEqual(state.receipts, progressed.receipts)
        self.assertEqual("left", progressed.group_map["g"].selected)
        with self.assertRaises(ModelError):
            derive_rewrite(progressed, MergeSelect("g", "right", "J"))


class AtomicCutRaceTests(unittest.TestCase):
    def fresh_race_state(self) -> HistoryState:
        return HistoryState(
            branches=(
                LiveBranch(
                    "old",
                    one("old-call", "source-cell"),
                    "gen:source",
                ),
            ),
            checkpoints=(
                NamedContract("k", one("saved", "target-cell")),
            ),
            policy=permissive_policy("source-cell", "target-cell"),
            policy_version=3,
            view_version=9,
        )

    def test_fresh_commit_wins_or_install_fences_old_generation(self) -> None:
        state = self.fresh_race_state()
        operation = RestoreReplace("old", "k")
        compiled = compile_cut(state, operation)
        invocation = GateInvocation("gen:source", "old-call", "source-cell")

        raced, event = commit_gate(state, invocation)
        self.assertEqual("fresh", event.kind)
        self.assertEqual(("source-cell",), raced.receipts)
        self.assertIn("old-call", raced.completed)
        with self.assertRaises(StaleCut):
            install_cut(raced, compiled)

        installed = install_cut(state, compiled)
        with self.assertRaises(ClosedGeneration):
            commit_gate(installed, invocation)

    def test_alias_commit_changes_chi_and_invalidates_same_receipt_seal(self) -> None:
        initial = self.fresh_race_state()
        state = HistoryState(
            branches=initial.branches,
            checkpoints=initial.checkpoints,
            receipts=("source-cell",),
            policy=initial.policy,
            policy_version=initial.policy_version,
            view_version=initial.view_version,
        )
        operation = RestoreReplace("old", "k")
        compiled = compile_cut(state, operation)
        invocation = GateInvocation("gen:source", "old-call", "source-cell")

        raced, event = commit_gate(state, invocation)
        self.assertEqual("alias", event.kind)
        self.assertEqual(state.receipts, raced.receipts)
        self.assertNotEqual(state.completed, raced.completed)
        with self.assertRaises(StaleCut):
            install_cut(raced, compiled)

        installed = install_cut(state, compiled)
        with self.assertRaises(ClosedGeneration):
            commit_gate(installed, invocation)

    def test_logical_frontier_order_is_seal_sensitive_and_commit_appends(self) -> None:
        base = self.fresh_race_state()
        state = replace(base, completed=("past:first", "past:second"))
        compiled = compile_cut(state, RestoreReplace("old", "k"))
        self.assertEqual(("past:first", "past:second"), compiled.seal.completed)

        same_members_different_order = replace(
            state,
            completed=("past:second", "past:first"),
        )
        self.assertEqual(
            set(state.completed), set(same_members_different_order.completed)
        )
        self.assertNotEqual(
            logical_frontier_digest(state.completed),
            logical_frontier_digest(same_members_different_order.completed),
        )
        self.assertEqual(
            logical_frontier_digest(state.completed),
            compiled.seal.completed_digest,
        )
        with self.assertRaises(StaleCut):
            install_cut(same_members_different_order, compiled)

        invocation = GateInvocation("gen:source", "old-call", "source-cell")
        committed, event = commit_gate(state, invocation)
        self.assertEqual("fresh", event.kind)
        self.assertEqual(
            ("past:first", "past:second", "old-call"),
            committed.completed,
        )
        retried, retry_event = commit_gate(committed, invocation)
        self.assertIsNone(retry_event)
        self.assertEqual(committed.completed, retried.completed)


if __name__ == "__main__":
    unittest.main()
