"""Unit tests for the finite authority-continuity model."""

from __future__ import annotations

import unittest

from authority_continuity import (
    Claim,
    downward_closure,
    is_downward_closed,
    make_state,
    plain_escape_counterexample,
    snapshot_local_impossibility_litmus,
    vector_leq,
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
        self.assertTrue(litmus["replace"]["safe"])
        self.assertFalse(litmus["live"]["safe"])
        self.assertEqual([1], litmus["replace"]["need"])
        self.assertEqual([2], litmus["live"]["need"])


if __name__ == "__main__":
    unittest.main()
