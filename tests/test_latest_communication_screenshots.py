"""Regression tests from the user's latest screenshot of action failures.

Keep model interpretation flexible, but preserve Godot-world authority.
These tests do not claim the local on-device GGUF will always generate
the intended plan; they verify the bridge accepts correct natural plans.
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.semantic import validated_steps, is_reflective_question
from test_semantic_planner import proposed, step, world
from test_action_completeness_review import AuditedBackend, audited

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


class TestCurrentScreenshots(unittest.TestCase):
    def test_turn_on_the_power_means_switch_the_visible_breaker(self):
        text = "Turn on the power"
        candidate = step("use", "breaker_box", "Turn on the power")
        self.assertEqual(validated_steps([candidate], text, world()),
                         ({"action": "use", "target": "breaker_box", "argument": ""},))

    def test_go_get_the_flashlight_is_pickup_not_clarification(self):
        text = "Eli, go get the flashlight"
        self.assertEqual(validated_steps([
            step("take", "flashlight", "go get the flashlight")
        ], text, world())[0]["action"], "take")

    def test_question_about_own_visible_breaker_lever_is_conversation(self):
        self.assertTrue(is_reflective_question(
            "Do you see the lever on the breaker box?"))
        self.assertTrue(is_reflective_question(
            "Can you see the power switch?"))
        self.assertTrue(is_reflective_question(
            "Eli, do you see the lever on the breaker box?"))
        self.assertFalse(is_reflective_question(
            "Do you see the lever? Go ahead and flip it."))

    def test_eli_vocative_does_not_block_semantic_second_pass(self):
        from ai_bridge.semantic import contains_explicit_action_request
        text = "Eli, go get the flashlight"
        self.assertTrue(contains_explicit_action_request(text))
        with TemporaryDirectory() as tmp:
            backend = AuditedBackend(
                proposed("clarify", [], "Which action do you mean?"),
                audited([step("take", "flashlight", "go get the flashlight")]))
            decision = Agent(
                backend, SessionStore(Path(tmp)), PERSONA).decide("eli", text, world())
            self.assertEqual(decision.action, "take")
            self.assertEqual(decision.target, "flashlight")
            self.assertEqual(backend.review_calls, 1)

    def test_go_to_desk_then_pick_up_flashlight_is_valid_sequence(self):
        text = "Move over to the desk and pick up the flashlight"
        expanded = world()
        expanded["objects"]["desk"] = {"visible": True,
                                         "description": "A wooden desk."}
        plans = [
            step("move_to", "desk", "Move over to the desk"),
            step("take", "flashlight", "pick up the flashlight")
        ]
        self.assertEqual([(s["action"], s["target"]) for s in
                          validated_steps(plans, text, expanded)],
                         [("move_to", "desk"), ("take", "flashlight")])

        with TemporaryDirectory() as tmp:
            backend = AuditedBackend(proposed("action", plans),
                                     audited([plans[1]]))
            agent = Agent(backend, SessionStore(Path(tmp)), PERSONA)
            decision = agent.decide("desk", text, expanded)
            self.assertEqual([(s["action"], s["target"])
                              for s in decision.actions],
                             [("move_to", "desk"), ("take", "flashlight")])

    def test_hypothetical_power_problem_does_not_authorize_flip(self):
        text = "What if you turned on the power?"
        # No present directive, despite naming the breaker.
        with self.assertRaises(Exception):
            validated_steps([
                step("use", "breaker_box", "turned on the power")
            ], text, world())


if __name__ == "__main__":
    unittest.main()
