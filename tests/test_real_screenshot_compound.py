"""The exact screenshot that silently performed only the first successful action.

A successful flashlight action is not enough: Eli must keep the complete,
engine-authorized sequence and give a truthful spoken survey at its end.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.intent import plan_actions

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"

SCREENSHOT = (
    "I see what's on the screen, and I see the flashlight. "
    "Go ahead and go grab it, turn it on, and take a look around the room, "
    "then tell me what you see."
)


def room(*, held=False, on=False, note=False):
    objects = {
        "flashlight": {"visible": True, "can_take": not held,
                       "description": ("The flashlight is in Eli's inventory."
                                       if held else "A flashlight on the desk.")},
        "breaker_box": {"visible": True, "description": "A breaker on the wall."},
        "keypad": {"visible": True, "description": "A red-glowing keypad."},
        "exit_door": {"visible": True, "description": "A heavy locked door."},
    }
    if note:
        objects["maintenance_note"] = {
            "visible": True, "description": "An unread folded note."}
    return {
        "room": "maintenance_chamber", "actor_at": "flashlight" if held else "room_center",
        "inventory": ["flashlight"] if held else [],
        "flashlight_on": on, "lights_on": note, "door_unlocked": False,
        "last_observation": "", "objects": objects,
    }


class NoInference:
    def __init__(self):
        self.calls = 0

    def respond(self, messages):
        self.calls += 1
        raise AssertionError("No model action should be inferred for these steps")

    def converse(self, messages):
        self.calls += 1
        raise AssertionError("A physical sequence must not become free-form chat")


class TestRealScreenshotSequence(unittest.TestCase):
    def test_exact_full_screenshot_is_three_sequential_actions(self):
        steps = plan_actions(SCREENSHOT)
        self.assertEqual(
            [(s.action, s.target, s.light_mode) for s in steps],
            [("take", "flashlight", ""),
             ("use", "flashlight", "on"),
             ("survey", "room", "")],
        )

    def test_survey_and_report_variants(self):
        cases = [
            ("Take a look around the room.", [("survey", "room")]),
            ("Have a look around the room and tell me what you see.",
             [("survey", "room")]),
            ("Pick up the flashlight, turn it on, take a look around the room, "
             "and let me know what you see.",
             [("take", "flashlight"), ("use", "flashlight"), ("survey", "room")]),
            ("Pick up the flashlight and switch it on, then look around the room "
             "and report back what you notice.",
             [("take", "flashlight"), ("use", "flashlight"), ("survey", "room")]),
        ]
        for message, expected in cases:
            with self.subTest(message=message):
                self.assertEqual([(s.action, s.target) for s in plan_actions(message)],
                                 expected)

    def test_screenshot_bridge_has_three_actions_with_zero_inference(self):
        with TemporaryDirectory() as folder:
            backend = NoInference()
            agent = Agent(backend, SessionStore(Path(folder)), PERSONA)
            decision = agent.decide("screenshot", SCREENSHOT, room())
            self.assertEqual(
                list(decision.actions),
                [
                    {"action": "take", "target": "flashlight", "argument": ""},
                    {"action": "use", "target": "flashlight", "argument": "on"},
                    {"action": "survey", "target": "room", "argument": ""},
                ])
            self.assertEqual((decision.action, decision.target), ("take", "flashlight"))
            self.assertIn("look around the room", decision.speech)
            self.assertEqual(backend.calls, 0)

            agent.outcome("screenshot", "take", "flashlight", True,
                          "Eli picked up the flashlight.", room(held=True))
            agent.outcome("screenshot", "use", "flashlight", True,
                          "Eli switched it on.", room(held=True, on=True))
            response = agent.outcome("screenshot", "survey", "room", True,
                                     "Eli looks around the room.", room(held=True, on=True))
            self.assertIn("flashlight on in my hand", response.speech)
            self.assertIn("breaker box", response.speech)
            self.assertIn("keypad", response.speech)
            self.assertIn("locked exit door", response.speech)
            self.assertNotIn("4317", response.speech)
            self.assertEqual(backend.calls, 0)
            self.assertEqual(
                [(x["action"], x["target"]) for x in agent.store.load("screenshot")["facts"]],
                [("take", "flashlight"), ("use", "flashlight"), ("survey", "room")])

    def test_trailing_unknown_instruction_never_falls_back_to_single_action(self):
        with TemporaryDirectory() as folder:
            backend = NoInference()
            agent = Agent(backend, SessionStore(Path(folder)), PERSONA)
            decision = agent.decide(
                "invalid",
                "Pick up the flashlight, dance a jig, and turn it on.",
                room())
            self.assertEqual((decision.action, decision.target), ("wait", ""))
            self.assertEqual(decision.actions, ())
            self.assertIn("whole sequence", decision.speech)
            self.assertEqual(backend.calls, 0)

    def test_reporting_before_survey_is_not_an_unverified_action(self):
        self.assertIsNone(plan_actions(
            "Pick up the flashlight, then tell me what you see.", strict=True))

    def test_hypothetical_does_not_authorize_sequence(self):
        self.assertEqual(plan_actions(
            "What if you grabbed the flashlight and looked around?"), ())


if __name__ == "__main__":
    unittest.main()
