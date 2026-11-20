"""Fast outcome recording and prompt-size regression checks for local CPU inference."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from ai_bridge.agent import Agent, MockBackend, SessionStore

ROOT = Path(__file__).resolve().parents[1]
WORLD = {
    "room": "maintenance_chamber", "inventory": [],
    "lights_on": False, "heard_knocks": False,
    "objects": {
        "flashlight": {"visible": True, "description": "Flashlight on the desk."},
        "hidden_note": {"visible": False, "description": "Secret key: 9999"},
    },
}


class CountingBackend:
    def __init__(self):
        self.calls = []
        self.mock = MockBackend()

    def respond(self, messages):
        self.calls.append(messages)
        return self.mock.respond(messages)


class TestLatency(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.backend = CountingBackend()
        self.store = SessionStore(Path(self.tmp.name))
        self.agent = Agent(self.backend, self.store,
                           ROOT / "data/characters/eli.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_outcome_is_fast_and_next_turn_knows_success(self):
        self.agent.decide("fast", "Pick up the flashlight", WORLD)
        self.assertEqual(len(self.backend.calls), 1)
        w = {**WORLD, "inventory": ["flashlight"]}
        answer = self.agent.outcome("fast", "take", "flashlight", True,
                                    "Eli picked up the flashlight.", w)
        self.assertIn("flashlight", answer.speech.lower())
        self.assertEqual(answer.action, "wait")
        self.assertEqual(len(self.backend.calls), 1, "Outcome must not trigger inference")
        answer = self.agent.decide("fast", "What are you holding?", w)
        self.assertIn("flashlight", answer.speech.lower())
        self.assertEqual(len(self.backend.calls), 2)
        self.assertIn("picked up the flashlight", json.dumps(self.backend.calls[1]).lower())

    def test_world_is_not_repeated_in_saved_history_or_leaked(self):
        self.agent.decide("compact", "Pick up the flashlight", WORLD)
        stored = self.store.load("compact")
        serialized = json.dumps(stored["history"])
        self.assertNotIn('"world"', serialized)
        self.assertNotIn("Secret key", json.dumps(self.backend.calls[0]))
        self.assertIn("Flashlight on the desk", json.dumps(self.backend.calls[0]))

    def test_legacy_snapshots_are_compacted_on_next_request(self):
        legacy = {"history": [
            {"role": "user", "content": "PLAYER REQUEST:\n" +
             json.dumps({"player_text": "I told you to look", "world":
                         {"huge": "old_snapshot" * 800}})},
            {"role": "assistant", "content": json.dumps(
                {"speech": "I can hear you.", "action": "wait", "target": ""})},
        ], "facts": []}
        self.store.save("old", legacy)
        self.agent.decide("old", "Are you there?", WORLD)
        prompt = json.dumps(self.backend.calls[-1])
        self.assertIn("I told you to look", prompt)
        self.assertNotIn("old_snapshot", prompt)

    def test_context_window_does_not_grow_forever(self):
        for i in range(17):
            self.agent.decide("long", "Check in %d" % i, WORLD)
        self.assertLessEqual(len(self.backend.calls[-1]), 14)
        self.assertLess(len(json.dumps(self.backend.calls[-1])), 5500)
        self.assertLessEqual(len(self.store.load("long")["history"]), 24)

    def test_failed_outcome_does_not_claim_success(self):
        result = self.agent.outcome("fail", "enter_code", "keypad", False,
                                    "The keypad rejected the code.", WORLD)
        self.assertIn("didn't accept", result.speech)
        self.assertEqual(len(self.backend.calls), 0)


if __name__ == "__main__":
    unittest.main()
