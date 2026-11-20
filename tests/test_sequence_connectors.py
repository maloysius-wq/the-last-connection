"""Regression tests for step connectors that must not be swallowed as chat."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.intent import plan_actions
from ai_bridge.agent import Agent, SessionStore

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"
WORLD = {
    "room": "maintenance_chamber", "inventory": [], "lights_on": False,
    "objects": {
        "flashlight": {"visible": True, "can_take": True, "description": "A flashlight."},
        "breaker_box": {"visible": True, "can_take": False, "description": "A breaker box."},
        "keypad": {"visible": True, "can_take": False, "description": "A keypad."},
        "exit_door": {"visible": True, "can_take": False, "description": "A locked door."},
    },
}


class NoInference:
    def respond(self, _messages):
        raise AssertionError("An explicit sequence should not require another LLM call")

    def converse(self, _messages):
        raise AssertionError("An explicit sequence should not become free-form dialogue")


class TestStepConnectors(unittest.TestCase):
    def test_then_after_comma_preserves_order(self):
        steps = plan_actions("Turn on the breaker, then read the note.")
        self.assertEqual([(step.action, step.target) for step in steps], [
            ("use", "breaker_box"), ("inspect", "maintenance_note")])

    def test_and_then_survey(self):
        steps = plan_actions(
            "Pick up the flashlight, then turn it on, and then look around the room.")
        self.assertEqual([(step.action, step.target, step.light_mode) for step in steps], [
            ("take", "flashlight", ""), ("use", "flashlight", "on"),
            ("survey", "room", "")])

    def test_then_between_commands_without_commas(self):
        steps = plan_actions("Switch on the flashlight then look around the room.")
        self.assertEqual([(s.action, s.target) for s in steps], [
            ("use", "flashlight"), ("survey", "room")])

    def test_sequence_words_at_sentence_start(self):
        steps = plan_actions(
            "First go to the breaker. Then turn it on. After that read the note.")
        self.assertEqual([(s.action, s.target) for s in steps], [
            ("move_to", "breaker_box"), ("use", "breaker_box"),
            ("inspect", "maintenance_note")])

    def test_descriptive_and_is_not_multiple_action_permission(self):
        self.assertEqual(plan_actions(
            "Go to the breaker and keypad, then inspect the door."), ())

    def test_no_unguessed_keypad_code(self):
        self.assertEqual(plan_actions(
            "Switch on the breaker, then enter a code on the keypad."), ())

    def test_physical_hypothetical_does_not_run(self):
        self.assertEqual(plan_actions(
            "I wonder what happens if you use the breaker and then open the door."), ())

    def test_agent_queues_note_only_after_verified_breaker(self):
        with TemporaryDirectory() as folder:
            agent = Agent(NoInference(), SessionStore(Path(folder)), PERSONA)
            result = agent.decide(
                "then_steps", "Turn on the breaker, then read the note.", WORLD)
        self.assertEqual([(x["action"], x["target"]) for x in result.actions], [
            ("use", "breaker_box"), ("inspect", "maintenance_note")])
        self.assertEqual((result.action, result.target), ("use", "breaker_box"))
        self.assertIn("then inspect", result.speech.lower())


if __name__ == "__main__":
    unittest.main()
