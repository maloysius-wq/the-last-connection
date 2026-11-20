"""Regression tests: Eli's speech must match completed world actions and true location."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, Decision, SessionStore
from ai_bridge.intent import classify

ROOT = Path(__file__).resolve().parents[1]

def world(at="room_center", observation="", *, lights=False):
    return {
        "room": "maintenance_chamber",
        "actor_at": at,
        "last_observation": observation,
        "inventory": [],
        "lights_on": lights,
        "objects": {
            "breaker_box": {"visible": True, "description": "A breaker box on the wall. Its lever is down."},
            "keypad": {"visible": True, "description": "A four-digit pad beside the door."},
            "exit_door": {"visible": True, "description": "The heavy door is locked."},
            "flashlight": {"visible": True, "description": "A flashlight on the desk."},
        },
    }


class SplitBackend:
    """A test double that reproduces two distinct generation modes."""
    def __init__(self, dialogue="I don't know.", action_speech="I already checked the keypad."):
        self.dialogue = dialogue
        self.action_speech = action_speech
        self.calls = []

    def respond(self, messages):
        self.calls.append(("structured", messages))
        return {"speech": self.action_speech, "action": "move_to",
                "target": "keypad", "emotion": "curious", "argument": ""}

    def converse(self, messages):
        self.calls.append(("converse", messages))
        return self.dialogue


class TestGroundedConversation(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def agent(self, backend):
        return Agent(backend, self.store, ROOT / "data/characters/eli.json")

    def test_move_to_breaker_not_mistaken_for_keypad(self):
        backend = SplitBackend()
        result = self.agent(backend).decide(
            "walk", "Go over to the breaker box", world(at="room_center"))
        self.assertEqual((result.action, result.target), ("move_to", "breaker_box"))
        self.assertIn("walk", result.speech.lower())
        self.assertIn("breaker box", result.speech.lower())
        self.assertNotIn("keypad", result.speech.lower())
        self.assertNotIn("already", result.speech.lower())
        self.assertEqual(backend.calls[0][0], "structured")

    def test_stand_by_breaker_is_explicit_movement(self):
        for phrase in ("Stand by the breaker box", "Move towards the breaker box",
                       "Walk over to the breaker box", "Head over to the breaker box"):
            with self.subTest(phrase=phrase):
                intent = classify(phrase)
                self.assertEqual((intent.kind, intent.action, intent.target),
                                 ("action", "move_to", "breaker_box"))

    def test_explicit_action_never_promises_past_completion(self):
        backend = SplitBackend(action_speech="I moved over there and looked at the keypad.")
        result = self.agent(backend).decide("inspect", "Inspect the breaker box", world())
        self.assertEqual((result.action, result.target), ("inspect", "breaker_box"))
        self.assertTrue(result.speech.startswith("I'll"))
        self.assertNotIn("keypad", result.speech)
        self.assertNotIn("moved", result.speech)

    def test_location_question_reads_true_engine_location(self):
        backend = SplitBackend(dialogue="I'm standing at the keypad.")
        result = self.agent(backend).decide(
            "where", "Where are you standing?", world(at="breaker_box"))
        self.assertEqual(result.action, "wait")
        self.assertIn("breaker box", result.speech.lower())
        self.assertNotIn("keypad", result.speech.lower())
        self.assertEqual(len(backend.calls), 0, "Known location needs no model call")

    def test_in_front_of_you_is_actual_position(self):
        backend = SplitBackend()
        result = self.agent(backend).decide(
            "near", "What's right in front of you?", world(at="breaker_box"))
        self.assertIn("lever is down", result.speech.lower())
        self.assertNotIn("keypad", result.speech.lower())

    def test_what_do_you_see_uses_confirmed_nearby_location(self):
        backend = SplitBackend(dialogue="The keypad is glowing.")
        reply = self.agent(backend).decide(
            "look", "What do you see?", world(at="breaker_box"))
        self.assertIn("breaker box", reply.speech.lower())
        self.assertNotIn("keypad", reply.speech.lower())
        self.assertEqual(len(backend.calls), 0)

    def test_autobiographical_memory_is_not_suppressed(self):
        backend = SplitBackend(dialogue="I went to school nearby. I don't know how I got here.")
        result = self.agent(backend).decide(
            "past", "What do you remember about your childhood?", world(at="breaker_box"))
        self.assertIn("went to school", result.speech)
        self.assertIn("how I got here", result.speech)

    def test_conversation_is_free_prose_not_forced_json(self):
        backend = SplitBackend(dialogue="I'm scared, but I'm trying to keep my head.")
        result = self.agent(backend).decide("chat", "Are you scared?", world(at="breaker_box"))
        self.assertEqual(result.action, "wait")
        self.assertIn("trying to keep my head", result.speech)
        self.assertEqual(backend.calls[0][0], "converse")
        sys = backend.calls[0][1][0]["content"]
        self.assertIn("Do not output JSON", sys)
        self.assertNotIn("Return one valid JSON", sys)
        prompt = backend.calls[0][1][-1]["content"]
        self.assertEqual("Are you scared?", prompt)
        self.assertIn('"actor_at":"breaker_box"', sys)
        self.assertIn('"speaker_can_reach_your_room":false', sys)

    def test_no_second_inference_after_physical_action(self):
        backend = SplitBackend()
        agent = self.agent(backend)
        result = agent.decide("turn", "Go over to the breaker box", world())
        self.assertEqual(len(backend.calls), 1)
        after = world(at="breaker_box", observation="Eli walked to the breaker box.")
        acknowledgment = agent.outcome(
            "turn", "move_to", "breaker_box", True, "Eli walked to the breaker box.", after)
        self.assertEqual(acknowledgment.action, "wait")
        self.assertEqual(len(backend.calls), 1)

    def test_confirmed_position_updates_conversation_focus(self):
        backend = SplitBackend(dialogue="I can see the lever on the breaker.")
        agent = self.agent(backend)
        agent.outcome("focus", "move_to", "breaker_box", True, "Eli reached the breaker.", world(at="breaker_box"))
        self.assertEqual(self.store.load("focus").get("focus"), "breaker_box")
        result = agent.decide("focus", "What do you think of it?", world(at="breaker_box"))
        self.assertEqual(result.action, "wait")
        self.assertIn("lever", result.speech)

    def test_false_unverified_movement_claim_is_corrected(self):
        backend = SplitBackend(dialogue="I went to the keypad.")
        result = self.agent(backend).decide(
            "false", "How are you feeling?", world(at="breaker_box"))
        self.assertNotIn("I went to the keypad", result.speech)
        self.assertIn("breaker box", result.speech.lower())
        self.assertEqual(result.action, "wait")

    def test_confirmed_observation_is_preferred_to_hallucination(self):
        backend = SplitBackend(dialogue="I just opened the door.")
        after = world(at="breaker_box", observation="Eli switched the breaker on.")
        result = self.agent(backend).decide(
            "obs", "What happened?", after)
        self.assertIn("breaker on", result.speech.lower())
        self.assertNotIn("opened the door", result.speech.lower())

    def test_legacy_speech_backend_still_works(self):
        class OldBackend:
            def respond(self, messages):
                return {"speech": "The breaker seems old.", "action": "inspect", "target": "keypad"}
        result = self.agent(OldBackend()).decide("old", "What do you think?", world())
        self.assertEqual(result.action, "wait")
        self.assertIn("breaker", result.speech.lower())


if __name__ == "__main__":
    unittest.main()
