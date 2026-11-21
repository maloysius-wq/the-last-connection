"""Live chat should not turn a gameshow prank into a room-puzzle checklist.

Eli sees the keypad, door and breaker himself. The camera operator is free to
joke, mislead or roleplay; Eli stays suspicious, emotionally present and
grounded in his own directly visible environment. Do not remove legitimate
questions about alternate camera angles or objects he cannot see.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from test_perspective import fresh_room

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"

GAMESHOW_START = "Hi Eli, whaddup, you're on a gameshow! Say hi to the audience!"
GAMESHOW_SECOND = "Oh don't worry, we can all see and hear you! You're on Escape That Room, channel 15!"
FIRST_REPLY = (
    "Whoa, hold up—what gameshow? I don’t even know where I am, and I’m not on a show. "
    "Are you sure you’re not just... watching a recording? "
    "And why would the audience care about me? "
    "I’m just a guy stuck in a maintenance room with no idea how I got here. "
    "Also, I don’t have a mic or a stage."
)
SECOND_REPLY = (
    "Escape That Room? Channel 15? "
    "I don’t see any lights or screens in here, and I’m not sure how I got here. "
    "If this is real, can you confirm what you see on your monitor right now? "
    "Are there any signs of a keypad, door, or power issues I should know about?"
)


class ChatOnly:
    def __init__(self, message):
        self.message = message
        self.calls = []
    def converse(self, messages):
        self.calls.append(messages)
        return self.message
    def respond(self, messages):
        raise AssertionError("A joke is not a physical action")


class SemanticChat(ChatOnly):
    def interpret(self, messages):
        self.calls.append(messages)
        return {"kind": "conversation", "steps": [], "speech": self.message,
                "emotion": "afraid"}


class TestCameraAndConversationRelevance(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))
        self.room = fresh_room()

    def tearDown(self):
        self.temp.cleanup()

    def speak(self, operator_text, reply, *, semantic=False, room=None):
        model = SemanticChat(reply) if semantic else ChatOnly(reply)
        agent = Agent(model, self.store, PERSONA)
        decision = agent.decide(
            "camera", operator_text, room or self.room)
        self.assertEqual((decision.action, decision.target), ("wait", ""))
        self.assertEqual(decision.actions, ())
        self.assertEqual(len(model.calls), 1)
        return decision.speech, model.calls[0][0]["content"]

    def test_gameshow_prank_retains_natural_suspicious_reaction(self):
        answer, prompt = self.speak(GAMESHOW_START, FIRST_REPLY)
        self.assertIn("what gameshow", answer)
        self.assertIn("audience care", answer)
        self.assertIn("mic or a stage", answer)
        self.assertIn("jokes, pranks", prompt)
        self.assertIn('"keypad"', prompt)

    def test_screenshot_removes_redundant_are_there_signs_question(self):
        for semantic in (False, True):
            with self.subTest(semantic=semantic):
                self.store.save("camera", {"history": [], "facts": []})
                answer, prompt = self.speak(
                    GAMESHOW_SECOND, SECOND_REPLY, semantic=semantic)
                self.assertIn("Escape That Room?", answer)
                self.assertIn("Channel 15?", answer)
                self.assertIn("monitor right now?", answer)
                self.assertNotIn("signs of a keypad", answer)
                self.assertNotIn("power issues", answer)
                self.assertIn("visible", prompt.lower())

    def test_do_you_see_keypad_that_i_am_looking_at_is_redundant(self):
        answer, _ = self.speak(
            "This is channel 15. Seriously!",
            "What? This isn't funny. Do you see a keypad over there?")
        self.assertEqual(answer, "What? This isn't funny.")

    def test_not_an_object_list_if_the_user_talks_to_him(self):
        answer, _ = self.speak(
            "I'm just playing with you, sorry.",
            "I don't believe that. Are there signs of a breaker box? "
            "You sound awfully calm for someone looking at me on camera.")
        self.assertNotIn("signs of a breaker", answer)
        self.assertIn("You sound awfully calm", answer)

    def test_legitimate_other_camera_angle_question_survives(self):
        answer, _ = self.speak(
            "You can see my camera feed?",
            "Can you see the keypad on your monitor from another angle?")
        self.assertIn("keypad", answer)

    def test_details_he_cannot_read_are_fair_questions(self):
        answer, _ = self.speak(
            "I'll help you.",
            "Can you see numbers on the keypad that I can't read from here?")
        self.assertIn("numbers on the keypad", answer)

    def test_hidden_not_yet_visible_object_can_be_asked_about(self):
        answer, _ = self.speak(
            "I see a table.",
            "Are there any signs of a note I can't see from here?")
        self.assertIn("signs of a note", answer)

    def test_does_not_discard_verified_observations(self):
        answer, _ = self.speak(
            "What do you see in there?",
            "I can see a keypad and a locked door. The overhead lights are out.",
            semantic=True)
        self.assertIn("keypad and a locked door", answer)
        self.assertIn("overhead lights are out", answer)

    def test_unseen_room_can_legitimately_be_asked_about(self):
        room = fresh_room()
        room["objects"]["keypad"]["visible"] = False
        answer, _ = self.speak(
            "Tell me about the door.",
            "Is there a keypad beside the door?", room=room)
        self.assertIn("keypad beside the door", answer)


if __name__ == "__main__":
    unittest.main()
