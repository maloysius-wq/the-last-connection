"""Regressions from the screenshot where world actions work but Eli sounds robotic.

We test the precise user phrasing, natural conversational answers, observation
versus character reaction, and rejection of only the *unsafe sentence* rather
than the whole response.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


def room(*, at="flashlight", holding=True, on=True):
    return {
        "room": "maintenance_chamber", "actor_at": at,
        "last_observation": ("Eli picked up the flashlight from the desk "
                             "and switched it on.") if holding else "",
        "inventory": ["flashlight"] if holding else [],
        "flashlight_on": on, "lights_on": False, "door_unlocked": False,
        "objects": {
            "flashlight": {
                "visible": True,
                "description": ("The flashlight is in Eli's inventory. It is on."
                                if holding else "A metal flashlight on the left desk.")},
            "breaker_box": {"visible": True,
                            "description": "A breaker box on the wall; its lever is down."},
            "keypad": {"visible": True,
                       "description": "A red four-digit keypad beside the door."},
            "exit_door": {"visible": True, "description": "A heavy locked door."},
        }
    }


class DialogueBackend:
    def __init__(self, words):
        self.words = words
        self.count = 0
    def converse(self, messages):
        self.count += 1
        return self.words
    def respond(self, messages):
        raise AssertionError("Conversation should not be a physical action")


class TestNaturalScreenshotResponses(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))
    def tearDown(self):
        self.temp.cleanup()
    def agent(self, backend):
        return Agent(backend, self.store, PERSONA)

    def test_first_contact_preserves_natural_reply(self):
        raw = ("Hi, Max. I'm Eli. I'm pretty confused about this place, "
               "but hearing you makes it a little easier.")
        backend = DialogueBackend(raw)
        answer = self.agent(backend).decide(
            "first", "Hi Eli, I'm Max. I have no idea how I got here, "
            "but I'm here to help you escape.", room(holding=False, on=False))
        self.assertEqual(answer.speech, raw)
        self.assertEqual(answer.action, "wait")
        self.assertEqual(backend.count, 1)

    def test_one_bad_action_sentence_doesnt_destroy_safe_intro(self):
        raw = ("Hi, Max. I'm Eli, and I don't know why I'm in here. "
               "I just picked up the flashlight. "
               "If you can see me, maybe you can help.")
        answer = self.agent(DialogueBackend(raw)).decide(
            "intro", "Hi Eli. I'm Max and I'm here to help you escape.",
            room(holding=False, on=False))
        self.assertIn("Hi, Max", answer.speech)
        self.assertIn("maybe you can help", answer.speech)
        self.assertNotIn("just picked up", answer.speech)
        self.assertNotIn("haven't touched anything new", answer.speech)

    def test_all_fictional_intro_receives_human_fallback_not_admin_report(self):
        raw = "I just picked up the flashlight. I switched it on."
        answer = self.agent(DialogueBackend(raw)).decide(
            "intro2", "Hi Eli, I'm Max. I don't know how I got here but I want to help you escape.",
            room(holding=False, on=False))
        self.assertIn("I'm Eli", answer.speech)
        self.assertIn("Max", answer.speech)
        self.assertNotIn("I haven't touched anything new", answer.speech)
        self.assertNotIn("I switched it on", answer.speech)

    def test_old_generic_safety_reply_is_replaced_after_greeting(self):
        reply = self.agent(DialogueBackend(
            "I haven't touched anything new. What would you like me to do?"
        )).decide("intro3", "Hi Eli, I'm Max. I'm here to help you escape.",
                 room(holding=False, on=False))
        self.assertIn("I'm Eli", reply.speech)
        self.assertNotIn("touched anything new", reply.speech)

    def test_screenshot_room_question_gets_actual_room_overview(self):
        backend = DialogueBackend("The flashlight is in Eli's inventory.")
        reply = self.agent(backend).decide(
            "overview", "Okay, what do you see in the room?", room())
        self.assertEqual(backend.count, 0)
        self.assertIn("desk", reply.speech)
        self.assertIn("breaker box", reply.speech)
        self.assertIn("keypad", reply.speech)
        self.assertIn("door", reply.speech)
        self.assertIn("flashlight", reply.speech)
        self.assertNotIn("Eli's inventory", reply.speech)
        self.assertNotIn("standing right by the flashlight", reply.speech)

    def test_position_question_refers_to_desk_not_held_prop(self):
        reply = self.agent(DialogueBackend("broken")).decide(
            "position", "Where are you standing?", room())
        self.assertIn("beside the desk", reply.speech)
        self.assertIn("in my hand", reply.speech)
        self.assertNotIn("Eli's inventory", reply.speech)

    def test_broad_survey_and_specific_location_differ(self):
        a = self.agent(DialogueBackend("broken"))
        overview = a.decide("two", "What can you see?", room(at="breaker_box"))
        location = a.decide("two", "What's right in front of you?", room(at="breaker_box"))
        self.assertIn("keypad", overview.speech)
        self.assertIn("breaker box", location.speech)
        self.assertNotIn("keypad", location.speech)

    def test_flashlight_acknowledgment_does_not_repeat_observation(self):
        agent = self.agent(DialogueBackend("Okay, the flashlight helps. I can see the table better now."))
        actual = room()
        confirmed = agent.outcome(
            "ack", "use", "flashlight", True,
            "Eli picked up the flashlight from the desk and switched it on.", actual)
        self.assertIn("table better now", confirmed.speech)
        self.assertNotIn("picked it up and switched it on", confirmed.speech)

    def test_truthful_flashlight_state_is_allowed_in_conversation(self):
        backend = DialogueBackend("The flashlight's on, so I can see a little better.")
        answer = self.agent(backend).decide(
            "true", "Does that light help?", room(holding=True, on=True))
        self.assertIn("flashlight's on", answer.speech.lower())
        self.assertIn("see a little better", answer.speech.lower())

    def test_untrue_flashlight_state_is_rejected_without_hallucinating(self):
        backend = DialogueBackend("The flashlight's on now.")
        answer = self.agent(backend).decide(
            "untrue", "Does that light help?", room(holding=False, on=False))
        self.assertNotIn("on now", answer.speech)
        self.assertIn("flashlight", answer.speech.lower())

    def test_question_about_flashlight_is_not_treated_as_a_pickup(self):
        backend = DialogueBackend("I've got a question about the flashlight. Is it charged?")
        answer = self.agent(backend).decide(
            "question", "What are you thinking?", room(holding=False, on=False))
        self.assertEqual(answer.speech, backend.words)

    def test_memory_from_before_room_is_not_rewritten(self):
        backend = DialogueBackend("I used to carry a flashlight when I went camping as a kid.")
        answer = self.agent(backend).decide(
            "memory", "Tell me about being outdoors.", room(holding=False, on=False))
        self.assertIn("camping", answer.speech)
        self.assertEqual(answer.speech, backend.words)

if __name__ == "__main__":
    unittest.main()
