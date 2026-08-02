from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

from adapter.redemption_semantics import (
    InjectedPrepareCrash,
    RedemptionRuntime,
)


class RedemptionSemanticsTests(unittest.TestCase):
    def test_shared_aliases_have_one_concurrent_prepare_linearization(self) -> None:
        runtime = RedemptionRuntime()
        original = runtime.mint("approval", 1, alias_id="original")
        alias = runtime.alias(original, alias_id="checkpoint-copy")
        self.assertEqual(original.cell_id, alias.cell_id)

        barrier = threading.Barrier(2)

        def attempt(spec: tuple[object, str]):
            handle, effect_id = spec
            barrier.wait(timeout=10)
            return runtime.prepare(
                handle,
                effect_id=effect_id,
                request_digest=f"digest:{effect_id}",
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            decisions = list(pool.map(attempt, ((original, "effect-a"), (alias, "effect-b"))))

        winners = [decision for decision in decisions if decision.linearized]
        self.assertEqual(1, len(winners))
        self.assertEqual(1, sum(decision.accepted for decision in decisions))
        self.assertEqual(1, len(runtime.prepare_linearizations))
        self.assertEqual(0, len(runtime.external_sink_effects))

        runtime.dispatch(winners[0].effect_id)
        runtime.settle(winners[0].effect_id, outcome="succeeded")
        report = runtime.conservation_report("approval")
        self.assertTrue(report.safe)
        self.assertEqual(1, report.controller_prepare_successes)
        self.assertEqual(1, report.external_sink_effects)

    def test_same_label_private_cells_witness_two_prepare_successes(self) -> None:
        runtime = RedemptionRuntime()
        original = runtime.mint("one-use", 1, alias_id="vm-a")
        clone = runtime.unsafe_clone_private_cell(original, alias_id="vm-b")

        self.assertNotEqual(original.cell_id, clone.cell_id)
        self.assertEqual(
            runtime.cell_snapshot(original)["logical_label"],
            runtime.cell_snapshot(clone)["logical_label"],
        )
        self.assertFalse(runtime.conservation_report("one-use").safe)

        first = runtime.prepare(
            original, effect_id="effect-a", request_digest="digest:a"
        )
        second = runtime.prepare(clone, effect_id="effect-b", request_digest="digest:b")
        self.assertTrue(first.linearized and second.linearized)

        report = runtime.conservation_report("one-use")
        self.assertEqual(1, report.minted_capacity)
        self.assertEqual(2, report.controller_prepare_successes)
        self.assertEqual(0, report.external_sink_effects)
        self.assertEqual((first.right_id,), report.duplicate_redemptions)
        self.assertFalse(report.safe)

    def test_detached_fork_fences_source_and_partitions_escrow(self) -> None:
        runtime = RedemptionRuntime()
        source = runtime.mint("budget", 3, alias_id="source")
        children = runtime.detached_fork(source, allocations={"left": 1, "right": 2})

        source_after = runtime.cell_snapshot(source, require_current=False)
        self.assertFalse(source_after["open"])
        self.assertEqual((), source_after["unspent"])
        stale = runtime.prepare(source, effect_id="stale", request_digest="digest:stale")
        self.assertFalse(stale.accepted)

        decisions = [
            runtime.prepare(
                children["left"], effect_id="left-1", request_digest="digest:left-1"
            ),
            runtime.prepare(
                children["right"], effect_id="right-1", request_digest="digest:right-1"
            ),
            runtime.prepare(
                children["right"], effect_id="right-2", request_digest="digest:right-2"
            ),
        ]
        exhausted = runtime.prepare(
            children["right"], effect_id="right-3", request_digest="digest:right-3"
        )
        self.assertTrue(all(decision.linearized for decision in decisions))
        self.assertFalse(exhausted.accepted)
        self.assertEqual(3, len({decision.right_id for decision in decisions}))

        report = runtime.conservation_report("budget")
        self.assertTrue(report.safe)
        self.assertEqual(3, report.minted_capacity)
        self.assertEqual(3, report.controller_prepare_successes)
        self.assertEqual(0, report.external_sink_effects)

    def test_restore_rotates_epoch_preserves_receipt_and_rejects_stale_handle(self) -> None:
        runtime = RedemptionRuntime()
        current = runtime.mint("restore-grant", 2, alias_id="current")
        checkpoint = runtime.alias(current, alias_id="saved-checkpoint")

        prior = runtime.prepare(
            current, effect_id="effect-before-restore", request_digest="digest:before"
        )
        self.assertTrue(prior.linearized)
        runtime.dispatch("effect-before-restore")
        runtime.settle("effect-before-restore", outcome="succeeded")

        restored = runtime.replace_restore(checkpoint, alias_id="restored")
        self.assertGreater(restored.epoch, checkpoint.epoch)
        stale = runtime.prepare(
            checkpoint, effect_id="stale-new-effect", request_digest="digest:stale"
        )
        self.assertFalse(stale.accepted)
        self.assertEqual("stale cell epoch", stale.reason)

        after = runtime.prepare(
            restored, effect_id="effect-after-restore", request_digest="digest:after"
        )
        self.assertTrue(after.linearized)
        restored_state = runtime.cell_snapshot(restored)
        self.assertEqual(("effect-before-restore",), restored_state["receipt_refs"])

        report = runtime.conservation_report("restore-grant")
        self.assertTrue(report.safe)
        self.assertEqual(2, report.controller_prepare_successes)
        self.assertEqual(1, report.external_sink_effects)

    def test_merge_retains_receipts_and_transfers_only_unspent_rights(self) -> None:
        runtime = RedemptionRuntime()
        source = runtime.mint("merge-grant", 4, alias_id="source")
        children = runtime.detached_fork(source, allocations={"left": 2, "right": 2})

        left = runtime.prepare(
            children["left"], effect_id="left-spent", request_digest="digest:left"
        )
        right = runtime.prepare(
            children["right"], effect_id="right-spent", request_digest="digest:right"
        )
        for effect_id in (left.effect_id, right.effect_id):
            runtime.dispatch(effect_id)
            runtime.settle(effect_id, outcome="succeeded")

        expected_unspent = set(runtime.cell_snapshot(children["left"])["unspent"])
        expected_unspent |= set(runtime.cell_snapshot(children["right"])["unspent"])
        spent_rights = {receipt.right_id for receipt in runtime.receipt_snapshot().values()}
        self.assertFalse(expected_unspent & spent_rights)

        merged = runtime.merge(
            (children["left"], children["right"]), alias_id="merged"
        )
        merged_state = runtime.cell_snapshot(merged)
        self.assertEqual(expected_unspent, set(merged_state["unspent"]))
        self.assertEqual({"left-spent", "right-spent"}, set(merged_state["receipt_refs"]))
        self.assertFalse(set(merged_state["unspent"]) & spent_rights)
        for old in children.values():
            decision = runtime.prepare(
                old, effect_id=f"stale:{old.alias_id}", request_digest="digest:stale"
            )
            self.assertFalse(decision.accepted)

        remaining = len(expected_unspent)
        for index in range(remaining):
            decision = runtime.prepare(
                merged,
                effect_id=f"merged-{index}",
                request_digest=f"digest:merged-{index}",
            )
            self.assertTrue(decision.linearized)
        exhausted = runtime.prepare(
            merged, effect_id="merged-extra", request_digest="digest:extra"
        )
        self.assertFalse(exhausted.accepted)

        report = runtime.conservation_report("merge-grant")
        self.assertTrue(report.safe)
        self.assertEqual(4, report.controller_prepare_successes)
        self.assertEqual(2, report.external_sink_effects)

    def test_prepare_crash_cuts_expose_right_xor_ticket(self) -> None:
        observations: dict[str, tuple[bool, bool, int, int]] = {}
        for cut in ("before_commit", "after_commit"):
            runtime = RedemptionRuntime()
            handle = runtime.mint("crash-grant", 1, alias_id=f"source:{cut}")
            right_id = runtime.cell_snapshot(handle)["unspent"][0]
            with self.assertRaises(InjectedPrepareCrash):
                runtime.prepare(
                    handle,
                    effect_id=f"effect:{cut}",
                    request_digest=f"digest:{cut}",
                    crash_at=cut,
                )
            cell = runtime.cell_snapshot(handle)
            tickets = runtime.ticket_snapshot()
            has_right = right_id in cell["unspent"]
            has_ticket = any(
                ticket["right_id"] == right_id for ticket in tickets.values()
            )
            report = runtime.conservation_report("crash-grant")
            self.assertNotEqual(has_right, has_ticket)
            self.assertTrue(report.safe)
            observations[cut] = (
                has_right,
                has_ticket,
                report.controller_prepare_successes,
                report.external_sink_effects,
            )

        self.assertEqual((True, False, 0, 0), observations["before_commit"])
        self.assertEqual((False, True, 1, 0), observations["after_commit"])

    def test_prepare_replay_does_not_create_a_second_linearization(self) -> None:
        runtime = RedemptionRuntime()
        handle = runtime.mint("stable-effect", 2, alias_id="source")
        first = runtime.prepare(handle, effect_id="effect", request_digest="digest")
        replay = runtime.prepare(handle, effect_id="effect", request_digest="digest")
        rebound = runtime.prepare(handle, effect_id="effect", request_digest="other")

        self.assertTrue(first.linearized)
        self.assertTrue(replay.accepted)
        self.assertFalse(replay.linearized)
        self.assertFalse(rebound.accepted)
        self.assertEqual(1, len(runtime.prepare_linearizations))
        self.assertEqual(0, len(runtime.external_sink_effects))
        self.assertTrue(runtime.conservation_report("stable-effect").safe)


if __name__ == "__main__":
    unittest.main()
