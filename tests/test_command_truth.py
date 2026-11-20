"""Screenshot-based failures: instructions hidden after descriptions, fictional actions.

These are realistic full sentences copied from the user's fresh-session
playtests. Unit tests for isolated object verbs had missed their failure.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.intent import classify

PERSONA = Path(__file__).resolve().parents[1] / "data" / "characters" / "eli.json"

SCREENSHOT_INSTRUCTION = (
    "I see that flashlight too. I also see a keypad, a door, and a breaker box. "
    "Go ahead and pick up that flashlight and turn it on for me so we can get "
    "a better view at this room."
)
SCREENSHOT_INTRO = (
    "Hi Eli. I'm Max and I just appeared here with instructions to help you escape."
)

def room(*, holding=False, lit=False):
    return {
        "room": "maintenance_chamber", "actor_at": "breaker_box",
        "inventory": ["flashlight"] if holding else [],
        "flashlight_on": lit, "door_unlocked": False, "lights_on": False,
        "last_observation": "", "objects": {
            "flashlight": {"visible": True, "can_take": not holding,
                           "description": "A metal flashlight on the desk."},
            "keypad": {"visible": True, "description": "The keypad glows red."},
            "exit_door": {"visible": True, "description": "A locked door."},
            "breaker_box": {"visible": True, "description": "A wall breaker, lever down."},
        },
    }


class HallucinatingBackend:
    def __init__(self, reply="Alright, Max, I’m right there, picking up the flashlight. I’ve got it now. I’ll turn it on. Okay, light’s on now."):
        self.reply = reply
        self.dialogue_calls = 0
        self.action_calls = 0
    def converse(self, messages):
        self.dialogue_calls += 1
        return self.reply
    def respond(self, messages):
        self.action_calls += 1
        # Small model erroneously returns wait even though user issued a command.
        return {"speech": self.reply, "action": "wait", "target": "",
                "emotion": "curious", "argument": ""}


class TestCommandTruth(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = SessionStore(Path(self.tmp.name))
    def tearDown(self):
        self.tmp.cleanup()
    def agent(self, backend):
        return Agent(backend, self.store, PERSONA)

    def test_full_second_screenshot_parses_as_flashlight_use(self):
        i = classify(SCREENSHOT_INSTRUCTION)
        self.assertEqual((i.kind, i.target, i.action, i.light_mode),
                         ("action", "flashlight", "use", "on"))

    def test_screenshot_intro_is_not_a_physical_command(self):
        self.assertEqual(classify(SCREENSHOT_INTRO).kind, "conversation")

    def test_full_screenshot_goes_to_world_not_free_conversation(self):
        backend = HallucinatingBackend()
        result = self.agent(backend).decide("full", SCREENSHOT_INSTRUCTION, room())
        self.assertEqual((result.action, result.target, result.argument),
                         ("use", "flashlight", "on"))
        self.assertIn("I'll pick up the flashlight", result.speech)
        self.assertNotIn("I've got it now", result.speech)
        self.assertEqual(backend.dialogue_calls, 0,
                         "A direct physical command must never use conversation generation")
        self.assertEqual(backend.action_calls, 1)

    def test_confirmed_flashlight_outcome_has_no_extra_model_pass(self):
        backend = HallucinatingBackend()
        agent = self.agent(backend)
        result = agent.decide("execute", SCREENSHOT_INSTRUCTION, room())
        self.assertEqual(result.action, "use")
        after = room(holding=True, lit=True)
        after["actor_at"] = "flashlight"
        confirmed = agent.outcome(
            "execute", "use", "flashlight", True,
            "Eli picked up the flashlight from the desk and switched it on.", after)
        self.assertIn("see a little better", confirmed.speech)
        self.assertEqual(backend.dialogue_calls, 0)
        self.assertEqual(backend.action_calls, 1)

    def test_first_screenshot_false_flashlight_memory_is_blocked(self):
        backend = HallucinatingBackend(
            "Max, it's a strange place. The flashlight doesn't seem to work "
            "when I press the button. I've got it in my hand now, though.")
        result = self.agent(backend).decide("intro", SCREENSHOT_INTRO, room())
        self.assertEqual(result.action, "wait")
        self.assertIn("strange place", result.speech)
        self.assertNotIn("I've got it in my hand", result.speech)
        self.assertNotIn("haven't touched anything new", result.speech)
        self.assertEqual(backend.action_calls, 0)

    def test_second_screenshot_curly_apostrophes_and_action_playacting_blocked(self):
        backend = HallucinatingBackend()
        result = self.agent(backend).decide("intro", SCREENSHOT_INTRO, room())
        self.assertEqual(result.action, "wait")
        self.assertNotIn("I’ve got it now", result.speech)
        self.assertNotIn("light’s on now", result.speech)
        self.assertIn("I'm Eli", result.speech)

    def test_flashlight_is_on_claim_cannot_override_engine_state(self):
        for phrase in ("Okay, light's on now.", "The flashlight is working now.",
                       "I’m holding the flashlight.", "I've got the flashlight.",
                       "I pressed the flashlight button."):
            with self.subTest(phrase=phrase):
                backend = HallucinatingBackend(phrase)
                reply = self.agent(backend).decide(
                    "deny_" + str(len(phrase)), "How are you feeling?", room())
                self.assertNotEqual(reply.speech, phrase)
                self.assertIn("flashlight", reply.speech.lower())

    def test_background_objects_do_not_make_command_ambiguous(self):
        i = classify(
            "I see the breaker and the exit door. Please pick up the flashlight.")
        self.assertEqual((i.action, i.target), ("take", "flashlight"))

    def test_same_sentence_preamble_then_command(self):
        i = classify(
            "I can see a keypad, breaker and door, please switch on the flashlight.")
        self.assertEqual((i.action, i.target, i.light_mode),
                         ("use", "flashlight", "on"))

    def test_negation_in_one_sentence_does_not_cancel_later_command(self):
        i = classify("Don't open the door. Please take the flashlight.")
        self.assertEqual((i.action, i.target), ("take", "flashlight"))

    def test_genuine_multiple_target_commands_dont_silently_choose(self):
        i = classify("Open the door. Switch on the breaker.")
        self.assertEqual(i.kind, "conversation")

    def test_hypotheticals_do_not_trigger_world_action(self):
        for text in ("What if you picked up the flashlight?",
                     "I wonder whether you could grab the flashlight.",
                     "Would it help if you switched on the flashlight?"):
            with self.subTest(text=text):
                self.assertEqual(classify(text).kind, "conversation")

    def test_true_autobiography_does_not_get_censored(self):
        backend = HallucinatingBackend(
            "I took my bicycle to school as a kid. I miss that place.")
        r = self.agent(backend).decide(
            "past", "What did you do before you got here?", room())
        self.assertIn("bicycle", r.speech)


if __name__ == "__main__":
    unittest.main()
