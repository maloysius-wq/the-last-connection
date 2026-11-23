"""Regression for the user's exact failed 2026-11-23 compound action.

Session eli_1795458733_9554: the first GGUF omitted breaker activation,
the independent reviewer correctly included it but cited "turn that on as
well" twice, once for move_to and once for use. Godot executed nothing.
The engine already walks to objects before operating them.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.semantic import PlanRejected, validated_steps
from test_semantic_planner import proposed, step, world
from test_action_completeness_review import AuditedBackend, audited

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"
PLAYER = ("Pick up the flashlight, turn it on, then go over to the breaker "
          "box and turn that on as well.")
FIRST = [
    step("take", "flashlight", "pick up the flashlight"),
    step("use", "flashlight", "turn it on", "on"),
    step("move_to", "breaker_box", "turn that on as well"),
]
REVIEW = FIRST + [
    step("use", "breaker_box", "turn that on as well"),
]
EXPECTED = (
    {"action": "take", "target": "flashlight", "argument": ""},
    {"action": "use", "target": "flashlight", "argument": "on"},
    {"action": "use", "target": "breaker_box", "argument": ""},
)


class ActualCompoundPlaytest(unittest.TestCase):
    def test_exact_exported_model_and_review_proposals_execute_all_goals(self):
        with TemporaryDirectory() as directory:
            backend = AuditedBackend(
                proposed("action", FIRST, "Okay, I'll grab the flashlight first."),
                audited(REVIEW, reason="Use breaker in addition to moving there"))
            agent = Agent(backend, SessionStore(Path(directory)), PERSONA)
            decision = agent.decide("eli_playtest", PLAYER, world())
            self.assertEqual(decision.actions, EXPECTED)
            self.assertEqual(decision.action, "take")
            self.assertEqual(backend.interpret_calls, 1)
            self.assertEqual(backend.review_calls, 1)

    def test_review_collapses_only_redundant_move_to_not_interaction(self):
        self.assertEqual(validated_steps(REVIEW, PLAYER, world()), EXPECTED)
        self.assertEqual(validated_steps(FIRST, PLAYER, world()), (
            EXPECTED[0], EXPECTED[1],
            {"action": "move_to", "target": "breaker_box", "argument": ""}
        ))

    def test_turn_it_on_refers_to_nearest_newly_named_prop(self):
        player = "Pick up the flashlight and turn it on. Go to the breaker box and turn it on."
        plan = [
            step("take", "flashlight", "Pick up the flashlight"),
            step("use", "flashlight", "turn it on", "on"),
            step("use", "breaker_box", "turn it on"),
        ]
        result = validated_steps(plan, player, world())
        self.assertEqual(result[-1], EXPECTED[-1])

    def test_unrelated_target_cannot_steal_bare_pronoun(self):
        player = "Pick up the flashlight, then go to the breaker box and turn that on."
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("take", "flashlight", "Pick up the flashlight"),
                step("use", "flashlight", "turn that on", "on"),
            ], player, world())

    def test_duplicate_approach_not_collapsed_when_user_only_requested_walk(self):
        player = "Go to the breaker box."
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("move_to", "breaker_box", "Go to the breaker box"),
                step("use", "breaker_box", "Go to the breaker box"),
            ], player, world())

    def test_duplicate_interaction_does_not_reuse_same_evidence(self):
        player = "Turn on the breaker."
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("use", "breaker_box", "Turn on the breaker"),
                step("use", "breaker_box", "Turn on the breaker"),
            ], player, world())

    def test_negated_and_hypothetical_do_not_get_authorized(self):
        for player, quote in (
            ("Don't turn on the breaker.", "turn on the breaker"),
            ("What if you turn on the breaker?", "turn on the breaker"),
        ):
            with self.subTest(player=player), self.assertRaises(PlanRejected):
                validated_steps([
                    step("move_to", "breaker_box", quote),
                    step("use", "breaker_box", quote),
                ], player, world())

    def test_separately_directed_walk_and_use_remain_independent(self):
        player = "Go to the breaker box, then flip the breaker."
        result = validated_steps([
            step("move_to", "breaker_box", "Go to the breaker box"),
            step("use", "breaker_box", "flip the breaker"),
        ], player, world())
        self.assertEqual(result, (
            {"action": "move_to", "target": "breaker_box", "argument": ""},
            EXPECTED[-1],
        ))


if __name__ == "__main__":
    unittest.main()
