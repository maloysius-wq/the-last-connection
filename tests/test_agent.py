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

    def test_length_limits(self):
        with self.assertRaises(InvalidRequest):
            self.agent.decide("test", "x" * 601, WORLD)


if __name__ == "__main__":
    unittest.main()
