"""Playtest regressions: emotional live dialogue without clipped character text."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from ai_bridge.agent import Agent, LlamaCppBackend, OllamaBackend, SessionStore

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


def world():
    return {
        "room": "maintenance_chamber", "actor_at": "keypad",
        "last_observation": "", "inventory": [],
        "lights_on": False, "flashlight_on": False, "door_unlocked": False,
        "objects": {
            "flashlight": {"visible": True, "description": "A flashlight on Eli's desk."},
            "keypad": {"visible": True, "description": "A four-digit keypad glowing red."},
            "breaker_box": {"visible": True, "description": "A breaker box."},
            "exit_door": {"visible": True, "description": "A locked door."},
        },
    }


class Stub:
    def __init__(self, reply):
        self.reply = reply
        self.messages = []
    def converse(self, messages):
        self.messages.append(messages)
        return self.reply
    def respond(self, messages):
        raise AssertionError("Questions should never trigger physical commands")


class TestLiveDialogue(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))
    def tearDown(self):
        self.temp.cleanup()
    def agent(self, speech):
        backend = Stub(speech)
        return Agent(backend, self.store, PERSONA), backend

    def test_output_does_not_slice_650_characters_or_last_word(self):
        first = ("I hear you, but I can't tell why the keypad behaves that way. "
                 "I'm scared this whole thing could be a trap. ")
        raw = first + ("I don't know who built this place, and I need to understand "
                       "what you're seeing from your side before I trust anyone. " * 6)
        agent, _ = self.agent(raw)
        reply = agent.decide("long", "Why do you think it is a trap?", world())
        self.assertTrue(reply.speech.endswith("."))
        self.assertNotIn(reply.speech[-1], ("a", ","))
        self.assertNotIn("before I trust anyone. I don't know", reply.speech)
        self.assertLess(len(reply.speech), len(raw))

    def test_incomplete_token_budget_tail_is_dropped_not_displayed(self):
        agent, _ = self.agent(
            "I'm not sure why that red indicator is lit. But it's definitely not just a")
        result = agent.decide("cut", "How do you figure that's what it's doing?", world())
        self.assertEqual(result.speech, "I'm not sure why that red indicator is lit.")

    def test_full_single_sentence_is_kept_without_trailing_period(self):
        agent, _ = self.agent("I don't know what you want from me")
        result = agent.decide("single", "What are you thinking?", world())
        self.assertEqual(result.speech, "I don't know what you want from me.")

    def test_realistic_opening_keeps_emotional_reply(self):
        raw = "Who are you? How can you see me? I'm sorry, I don't know if I can trust you."
        agent, backend = self.agent(raw)
        reply = agent.decide("intro", "Hi, Eli. I'm here to help.", world())
        self.assertEqual(reply.speech, raw)
        self.assertIn("frightened and distrustful", backend.messages[0][0]["content"])
        self.assertEqual(len(backend.messages), 1)

    def test_false_numeric_keypad_sequence_does_not_become_fact(self):
        agent, _ = self.agent(
            "After 7733, it went from slow to fast. The first pulse was at 12 seconds. "
            "It seems to be counting down. I'm scared to touch the keypad.")
        agent.store.save("keypad", {"history": [], "facts": [], "referent": "keypad"})
        reply = agent.decide("keypad", "How do you figure that's what it's doing?", world())
        self.assertNotIn("7733", reply.speech)
        self.assertNotIn("12 seconds", reply.speech)
        self.assertIn("scared", reply.speech)
        self.assertEqual(reply.action, "wait")

    def test_detailed_story_request_can_be_longer(self):
        text = ("I remember the quiet. " * 5) + "I remember the room I came from."
        agent, _ = self.agent(text)
        reply = agent.decide("story", "Tell me the full story about before you came here.", world())
        self.assertGreater(reply.speech.count("remember"), 3)
        self.assertTrue(reply.speech.endswith("."))

    def test_dialogue_context_warns_against_invented_keypad_timing(self):
        agent, backend = self.agent("I'm not sure. It's making me nervous.")
        agent.decide("prompt", "Why is the red light on?", world())
        prompt = backend.messages[0][0]["content"]
        self.assertIn("numeric sequences", prompt)
        self.assertIn("short, natural", prompt)
        self.assertIn("CANONICAL PERSPECTIVE", prompt)

    def test_local_backends_have_headroom_for_sentence_completion(self):
        class Reply:
            def __init__(self, payload):
                self.data = json.dumps(payload).encode()
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, limit):
                return self.data
        captured = []
        def fake_urlopen(req, timeout):
            payload = json.loads(req.data)
            captured.append(payload)
            if "options" in payload:
                return Reply({"message": {"content": "I'm here."}})
            return Reply({"choices": [{"message": {"content": "I'm here."}}]})
        with patch("ai_bridge.agent.request.urlopen", side_effect=fake_urlopen):
            self.assertEqual(OllamaBackend().converse([]), "I'm here.")
            self.assertEqual(LlamaCppBackend().converse([]), "I'm here.")
        self.assertGreaterEqual(captured[0]["options"]["num_predict"], 320)
        self.assertGreaterEqual(captured[1]["max_tokens"], 320)


if __name__ == "__main__":
    unittest.main()
