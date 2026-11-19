import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, Decision, InvalidRequest, MockBackend, SessionStore

ROOT = Path(__file__).resolve().parents[1]
WORLD = {
    "room": "maintenance_chamber",
    "inventory": [],
    "objects": {
        "flashlight": {"visible": True, "description": "A flashlight on a desk.", "can_take": True, "reachable": True},
        "hidden_key": {"visible": False, "description": "A concealed key."},
    },
}


class TestAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = SessionStore(Path(self.tmp.name))
        self.agent = Agent(MockBackend(), self.store, ROOT / "data/characters/eli.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_action_is_structured_and_saved(self):
        decision = self.agent.decide("test", "Pick up the flashlight", WORLD)
        self.assertEqual(decision.action, "take")
        self.assertEqual(decision.target, "flashlight")
        self.assertEqual(len(self.store.load("test")["history"]), 2)

    def test_outcome_is_reported_only_after_execution(self):
        decision = self.agent.outcome("test", "take", "flashlight", True,
                                      "Picked up flashlight", {**WORLD, "inventory": ["flashlight"]})
        self.assertEqual(decision.action, "wait")
        self.assertEqual(len(self.store.load("test")["facts"]), 1)

    def test_hallucinated_target_blocked(self):
        response = Agent._decision({"speech": "I found it!", "action": "take", "target": "hidden_key"}, WORLD)
        self.assertEqual(response.action, "wait")
        self.assertIn("don't see", response.speech)

    def test_unknown_target_blocked(self):
        response = Agent._decision({"speech": "Done", "action": "use", "target": "magic_button"}, WORLD)
        self.assertEqual(response.action, "wait")

    def test_bad_session_rejected(self):
        with self.assertRaises(InvalidRequest):
            self.agent.decide("../escape", "Hello", WORLD)

    def test_empty_input_rejected(self):
        with self.assertRaises(InvalidRequest):
            self.agent.decide("test", "", WORLD)

    def test_session_persists_across_agent_instances(self):
        self.agent.decide("save_me", "Hello Eli", WORLD)
        new_agent = Agent(MockBackend(), SessionStore(Path(self.tmp.name)), ROOT / "data/characters/eli.json")
        self.assertEqual(len(new_agent.store.load("save_me")["history"]), 2)

    def test_outcome_forces_wait(self):
        forced = Agent._decision({"speech": "Hello", "action": "take", "target": "flashlight"}, WORLD, outcome=True)
        self.assertEqual(forced.action, "wait")


    def test_keypad_requires_exactly_four_digits(self):
        world = {**WORLD, "objects": {**WORLD["objects"],
                    "keypad": {"visible": True, "description": "Four-digit keypad"}}}
        invalid = Agent._decision({"speech": "I'll do it", "action": "enter_code",
                                   "target": "keypad", "argument": "43171"}, world)
        self.assertEqual(invalid.action, "wait")
        valid = Agent._decision({"speech": "Trying it", "action": "enter_code",
                                 "target": "keypad", "argument": "4317"}, world)
        self.assertEqual(valid.action, "enter_code")
        self.assertEqual(valid.argument, "4317")

    def test_code_cannot_target_other_objects(self):
        output = Agent._decision({"speech": "I'll open it", "action": "enter_code",
                                  "target": "flashlight", "argument": "4317"}, WORLD)
        self.assertEqual(output.action, "wait")

    def test_non_code_actions_discard_arguments(self):
        output = Agent._decision({"speech": "Checking", "action": "inspect",
                                  "target": "flashlight", "argument": "4317"}, WORLD)
        self.assertEqual(output.argument, "")

    def test_outcome_never_requests_more_actions(self):
        output = Agent._decision({"speech": "Done", "action": "enter_code",
                                  "target": "keypad", "argument": "4317"}, WORLD, outcome=True)
        self.assertEqual(output.action, "wait")
        self.assertEqual(output.argument, "")

    def test_mock_understands_keypad_entry(self):
        world = {**WORLD, "objects": {**WORLD["objects"],
                    "keypad": {"visible": True, "description": "Keypad"}}}
        output = self.agent.decide("code", "Enter 4317 on the keypad", world)
        self.assertEqual((output.action, output.target, output.argument),
                         ("enter_code", "keypad", "4317"))

    def test_length_limits(self):
        with self.assertRaises(InvalidRequest):
            self.agent.decide("test", "x" * 601, WORLD)


if __name__ == "__main__":
    unittest.main()
