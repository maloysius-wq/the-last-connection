"""Real playtest: 'pin pad' plus 'take a look' must move Eli, not just talk."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.intent import classify

PERSONA = Path(__file__).resolve().parents[1] / "data" / "characters" / "eli.json"

WORLD = {
    "room": "maintenance_chamber",
    "actor_at": "flashlight",
    "inventory": ["flashlight"],
    "flashlight_on": True,
    "objects": {
        "flashlight": {"visible": True, "description": "Eli is holding the flashlight."},
        "keypad": {"visible": True,
                   "description": "A four-digit keypad with a red-glowing indicator."},
        "breaker_box": {"visible": True, "description": "A wall-mounted breaker."},
        "exit_door": {"visible": True, "description": "The locked exit door."},
    },
}


class ConfusedBackend:
    def __init__(self):
        self.structured_calls = 0
        self.conversation_calls = 0

    def respond(self, messages):
        self.structured_calls += 1
        # Simulates exactly the bug: model claims to be walking but offers wait.
        return {"speech": "I'm already on my way to the keypad, the screen glows red!",
                "action": "wait", "target": "", "argument": "", "emotion": "curious"}

    def converse(self, messages):
        self.conversation_calls += 1
        return "I'm already on my way to the keypad."


class TestPinPadCommand(unittest.TestCase):
    def test_exact_user_screenshot_instruction(self):
        intent = classify("Okay great. Go over to the pin pad and take a look at the red glowing screen.")
        self.assertEqual((intent.kind, intent.action, intent.target),
                         ("action", "inspect", "keypad"))

    def test_go_to_pin_pad_will_move(self):
        for phrase in ("Go over to the pin pad", "Walk to the pinpad",
                       "Stand by the PIN pad", "Head to the keypad"):
            with self.subTest(phrase=phrase):
                intent = classify(phrase)
                self.assertEqual((intent.kind, intent.action, intent.target),
                                 ("action", "move_to", "keypad"))

    def test_take_a_look_means_inspect_not_take(self):
        for phrase in ("Take a look at the pin pad",
                       "Go to the keypad and take a closer look",
                       "Have a look at the red glowing screen",
                       "Look at the red light"):
            with self.subTest(phrase=phrase):
                intent = classify(phrase)
                self.assertEqual((intent.kind, intent.action, intent.target),
                                 ("action", "inspect", "keypad"))

    def test_no_accidental_flashlight_pickup_regression(self):
        self.assertEqual((classify("Take the flashlight").action,
                          classify("Take the flashlight").target), ("take", "flashlight"))
        self.assertEqual((classify("Pick up the flashlight and turn it on").action,
                          classify("Pick up the flashlight and turn it on").target),
                         ("use", "flashlight"))

    def test_pin_pad_code_entry(self):
        intent = classify("Enter 4317 on the pin pad")
        self.assertEqual((intent.action, intent.target), ("enter_code", "keypad"))

    def test_questions_about_screen_do_not_start_action(self):
        for phrase in ("What is the red screen?", "Why is the pin pad red?",
                       "Would it help if you looked at the glowing screen?"):
            with self.subTest(phrase=phrase):
                self.assertEqual(classify(phrase).kind, "conversation")

    def test_decide_routes_exact_instruction_to_world_action_even_if_model_waits(self):
        with TemporaryDirectory() as temporary:
            backend = ConfusedBackend()
            agent = Agent(backend, SessionStore(Path(temporary)), PERSONA)
            reply = agent.decide(
                "pinpad", "Okay great. Go over to the pin pad and take a look at the red glowing screen.",
                WORLD)
        self.assertEqual((reply.action, reply.target), ("inspect", "keypad"))
        self.assertIn("closer look at the keypad", reply.speech.lower())
        self.assertEqual(backend.structured_calls, 1)
        self.assertEqual(backend.conversation_calls, 0)

    def test_conversation_cannot_claim_movement_is_underway_without_action(self):
        with TemporaryDirectory() as temporary:
            backend = ConfusedBackend()
            agent = Agent(backend, SessionStore(Path(temporary)), PERSONA)
            result = agent.decide("chat", "What do you think the red light means?", WORLD)
        self.assertEqual(result.action, "wait")
        self.assertNotIn("on my way", result.speech.lower())
        self.assertIn("haven't started moving", result.speech.lower())
        self.assertEqual(backend.conversation_calls, 1)
        self.assertEqual(backend.structured_calls, 0)

    def test_decide_go_to_pinpad_then_target_is_keypad(self):
        with TemporaryDirectory() as temporary:
            backend = ConfusedBackend()
            agent = Agent(backend, SessionStore(Path(temporary)), PERSONA)
            reply = agent.decide("move", "Go over to the pin pad", WORLD)
        self.assertEqual((reply.action, reply.target), ("move_to", "keypad"))
        self.assertIn("walk over", reply.speech.lower())


if __name__ == "__main__":
    unittest.main()
