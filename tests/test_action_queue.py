"""Sequential action plans grounded in the player's full multi-step instruction.

No LLM can invent a plan. The world remains the only action-result authority.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.intent import plan_actions, classify

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"

SCREENSHOT = (
    "I understand. I hope to earn your trust through this. "
    "I see a flashlight on a desk next to you. "
    "Let's start by having you pick that up, turn on the light, and "
    "look around the room to see if you notice anything new."
)


def room(*, flashlight=False, breaker=False):
    objects = {
        "flashlight": {"visible": True, "description": "A flashlight on the desk."},
        "breaker_box": {"visible": True, "description": "Breaker lever down."},
        "keypad": {"visible": True, "description": "A red keypad by the door."},
        "exit_door": {"visible": True, "description": "A heavy locked exit door."},
    }
    if breaker:
        objects["maintenance_note"] = {
            "visible": True, "description": "A folded note on the desk."}
    return {
        "room": "maintenance_chamber", "objects": objects,
        "inventory": ["flashlight"] if flashlight else [],
        "flashlight_on": flashlight, "lights_on": breaker,
        "door_unlocked": False, "actor_at": "room_center",
        "last_observation": "",
    }


class InstrumentedBackend:
    def __init__(self):
        self.respond_calls = 0
        self.converse_calls = 0

    def respond(self, messages):
        self.respond_calls += 1
        return {"speech": "Okay.", "action": "wait", "target": ""}

    def converse(self, messages):
        self.converse_calls += 1
        return "There are a few things in here."


class TestActionPlanParser(unittest.TestCase):
    def as_pairs(self, message, focus=""):
        return [(a.action, a.target, a.light_mode, a.argument)
                for a in plan_actions(message, focus)]

    def test_exact_screenshot_yields_three_actions_in_order(self):
        self.assertEqual(self.as_pairs(SCREENSHOT), [
            ("take", "flashlight", "", ""),
            ("use", "flashlight", "on", ""),
            ("survey", "room", "", ""),
        ])

    def test_simple_command_sequence_uses_same_object_pronoun(self):
        self.assertEqual(self.as_pairs("Pick up the flashlight and turn it on."), [
            ("take", "flashlight", "", ""),
            ("use", "flashlight", "on", ""),
        ])

    def test_multiple_physical_targets_in_order(self):
        self.assertEqual(self.as_pairs("Go to the breaker box and inspect it."), [
            ("move_to", "breaker_box", "", ""),
            ("inspect", "breaker_box", "", ""),
        ])

    def test_open_door_then_breaker_is_an_actual_queue(self):
        self.assertEqual(self.as_pairs("Open the door. Switch on the breaker."), [
            ("use", "exit_door", "", ""),
            ("use", "breaker_box", "", ""),
        ])

    def test_restoring_power_can_reveal_a_note(self):
        self.assertEqual(self.as_pairs("Turn on the breaker box. Read the maintenance note."), [
            ("use", "breaker_box", "", ""),
            ("inspect", "maintenance_note", "", ""),
        ])

    def test_keypad_digits_only_from_player(self):
        self.assertEqual(self.as_pairs("Switch on the breaker. Enter 4317 on the keypad."), [
            ("use", "breaker_box", "", ""),
            ("enter_code", "keypad", "", "4317"),
        ])
        self.assertEqual(self.as_pairs("Enter the code on the keypad."), [])

    def test_do_not_guess_which_light_without_a_referent(self):
        self.assertEqual(self.as_pairs("Turn on the light."), [])
        self.assertEqual(self.as_pairs("Turn on the light.", "flashlight"), [
            ("use", "flashlight", "on", ""),
        ])

    def test_one_direct_room_survey(self):
        self.assertEqual(self.as_pairs("Look around the room."), [
            ("survey", "room", "", ""),
        ])

    def test_story_and_questions_do_not_trigger_actions(self):
        for message in (
            "I see a flashlight on the desk.",
            "What do you see in the room?",
            "What if you picked up the flashlight and turned it on?",
            "I wonder if you could switch on the light.",
            "Would it help if you switched on the flashlight?",
            "I was thinking about looking around the room.",
        ):
            with self.subTest(message=message):
                self.assertEqual(plan_actions(message), ())

    def test_never_guess_ambiguous_pronouns(self):
        self.assertEqual(
            self.as_pairs("I see a flashlight and a keypad. Pick that up."),
            [])

    def test_more_than_five_actions_is_rejected_whole(self):
        self.assertEqual(self.as_pairs(
            "Go to the breaker box. Inspect it. Go to the keypad. "
            "Inspect it. Go to the door. Inspect it."), [])

    def test_unsupported_step_aborts_whole_plan(self):
        self.assertEqual(self.as_pairs(
            "Pick up the flashlight, dance a jig, and switch it on."), [])

    def test_negated_description_does_not_cancel_later_command(self):
        self.assertEqual(self.as_pairs(
            "Don't touch the door. Pick up the flashlight."), [
                ("take", "flashlight", "", ""),
            ])


class TestDecisionQueue(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.backend = InstrumentedBackend()
        self.agent = Agent(self.backend, SessionStore(Path(self.temp.name)), PERSONA)

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_player_utterance_returns_grounded_plan_not_dialogue(self):
        decision = self.agent.decide("screen", SCREENSHOT, room())
        self.assertEqual((decision.action, decision.target), ("take", "flashlight"))
        self.assertEqual(list(decision.actions), [
            {"action": "take", "target": "flashlight", "argument": ""},
            {"action": "use", "target": "flashlight", "argument": "on"},
            {"action": "survey", "target": "room", "argument": ""},
        ])
        self.assertIn("look around the room", decision.speech)
        self.assertIn("stop if something doesn't work", decision.speech)
        self.assertNotIn("I've done", decision.speech)
        self.assertEqual(self.backend.respond_calls, 0)
        self.assertEqual(self.backend.converse_calls, 0)

    def test_outcomes_are_logged_without_model_calls(self):
        self.agent.decide("events", SCREENSHOT, room())
        first = self.agent.outcome(
            "events", "take", "flashlight", True, "Eli picked it up.",
            room(flashlight=True), speak=False)
        second = self.agent.outcome(
            "events", "use", "flashlight", True, "Eli switched it on.",
            room(flashlight=True), speak=False)
        third = self.agent.outcome(
            "events", "survey", "room", True,
            "Eli looks around. The door is locked.", room(flashlight=True),
            speak=False)
        self.assertEqual((first.action, second.action, third.action),
                         ("wait", "wait", "wait"))
        self.assertEqual(self.backend.respond_calls + self.backend.converse_calls, 0)
        facts = self.agent.store.load("events")["facts"]
        self.assertEqual([(f["action"], f["target"]) for f in facts],
                         [("take", "flashlight"), ("use", "flashlight"), ("survey", "room")])

    def test_breaker_can_reveal_later_note_in_same_plan(self):
        result = self.agent.decide(
            "note", "Turn on the breaker box. Read the maintenance note.", room())
        self.assertEqual([step["target"] for step in result.actions],
                         ["breaker_box", "maintenance_note"])

    def test_missing_first_target_does_not_start_partial_queue(self):
        snapshot = room()
        snapshot["objects"].pop("flashlight")
        result = self.agent.decide(
            "missing", "Pick up the flashlight. Look around.", snapshot)
        self.assertEqual(result.action, "wait")
        self.assertEqual(result.actions, ())

    def test_single_question_remains_conversation(self):
        result = self.agent.decide(
            "ask", "Are you frightened?", room())
        self.assertEqual(result.action, "wait")
        self.assertEqual(self.backend.converse_calls, 1)

    def test_single_room_survey_uses_physical_action_not_conversation(self):
        result = self.agent.decide(
            "look", "Look around the room.", room())
        self.assertEqual((result.action, result.target), ("survey", "room"))
        self.assertEqual(self.backend.converse_calls, 0)

if __name__ == "__main__":
    unittest.main()
