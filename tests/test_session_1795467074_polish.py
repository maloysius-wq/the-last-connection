"""Regressions from the 2026-11-23 exported player session.

These checks protect the single-pass GGUF planner's natural-language freedom
while separating observations, reversible interactions, and terminal escape.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.goals import GOAL_INSTRUCTIONS, GoalRejected, validate_goals
from test_semantic_planner import world

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


def goal(action, target, argument=""):
    return {"action": action, "target": target, "argument": argument}


NOTE = {"action": "inspect", "target": "maintenance_note", "success": True,
        "description": "The maintenance note reads: 'RESET SEQUENCE 4317'. Don't listen to the knocking."}


class LocalModel:
    def __init__(self, goals, reply):
        self.goals, self.reply = goals, reply
        self.planned = []
        self.reactions = []

    def plan_goals(self, messages):
        self.planned.append(messages)
        return {"kind": "action", "speech": "I'll try that.",
                "emotion": "curious", "goals": self.goals}

    def converse(self, messages):
        self.reactions.append(messages)
        return self.reply


class SessionPolishTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def agent(self, model):
        return Agent(model, self.store, PERSONA)

    def test_exact_uploaded_unlocked_door_check_does_not_escape(self):
        # Actual GGUF proposal: first 'use exit_door' then 'inspect exit_door'.
        # No user-language parsing: prefer the explicit safe inspection in
        # this internally contradictory ENGINE plan.
        room = world()
        room["door_unlocked"] = True
        words = "I see that the pinpad turned green. Check if the door is unlocked now"
        interpreted = validate_goals([
            goal("use", "exit_door"), goal("inspect", "exit_door")
        ], room, words, [NOTE])
        self.assertEqual(interpreted, (goal("inspect", "exit_door"),))
        model = LocalModel([
            goal("use", "exit_door"), goal("inspect", "exit_door")
        ], "I checked the latch.")
        decision = self.agent(model).decide("door_check", words, room)
        self.assertEqual(decision.actions, (goal("inspect", "exit_door"),))
        self.assertEqual(len(model.planned), 1)

    def test_explicit_escape_still_valid_and_terminal(self):
        room = world()
        room["door_unlocked"] = True
        self.assertEqual(validate_goals([goal("use", "exit_door")], room,
                                        "Open the door and get out", []),
                         (goal("use", "exit_door"),))
        self.assertEqual(validate_goals([
            goal("enter_code", "keypad", "4317"), goal("use", "exit_door")
        ], room, "Enter 4317, then leave the room", []), (
            goal("enter_code", "keypad", "4317"), goal("use", "exit_door")))
        with self.assertRaises(GoalRejected):
            validate_goals([
                goal("use", "exit_door"), goal("inspect", "breaker_box")
            ], room, "Exit then inspect the breaker", [])

    def test_survey_capability_retains_action_intent(self):
        self.assertIn("A direct request to look around", GOAL_INSTRUCTIONS)
        self.assertIn("is survey/room", GOAL_INSTRUCTIONS)
        model = LocalModel([goal("survey", "room")],
                           "The room's cramped, and I don't like the door.")
        decision = self.agent(model).decide(
            "survey_request",
            "Take a look around the room and tell me what you can see.",
            world())
        self.assertEqual(decision.actions, (goal("survey", "room"),))
        self.assertEqual(len(model.planned), 1)

    def test_confirmed_note_code_can_be_said_after_keypad_accepts_it(self):
        room = world(note=True)
        room["lights_on"] = True
        model = LocalModel([goal("enter_code", "keypad", "known")],
                           "I entered 4317. The keypad accepted it.")
        self.store.save("known_code", {"history": [], "facts": [NOTE]})
        agent = self.agent(model)
        decision = agent.decide("known_code",
                                "Enter that code on the pin pad.", room)
        self.assertEqual(decision.actions, (goal("enter_code", "keypad", "4317"),))
        room["door_unlocked"] = True
        reaction = agent.outcome(
            "known_code", "enter_code", "keypad", True,
            "The keypad accepted the code. Its indicator is green; the exit door unlocked.",
            room)
        self.assertIn("4317", reaction.speech)
        facts = self.store.load("known_code")["facts"]
        self.assertEqual(facts[-1]["entered_code"], "4317")
        self.assertEqual(len(model.reactions), 1)

    def test_explicitly_entered_code_is_remembered_without_note(self):
        room = world()
        room["lights_on"] = True
        model = LocalModel([goal("enter_code", "keypad", "1234")],
                           "I tried 1234. The keypad accepted it.")
        agent = self.agent(model)
        decision = agent.decide("typed_code", "Type 1234 into the keypad.", room)
        self.assertEqual(decision.actions[0]["argument"], "1234")
        room["door_unlocked"] = True
        reply = agent.outcome("typed_code", "enter_code", "keypad", True,
                              "The keypad accepted the code.", room)
        self.assertIn("1234", reply.speech)
        self.assertEqual(self.store.load("typed_code")["facts"][-1]["entered_code"], "1234")

    def test_fabricated_unverified_number_cannot_be_spoken(self):
        room = world()
        room["lights_on"] = True
        model = LocalModel([], "I entered 9999. It worked.")
        answer = self.agent(model).outcome(
            "fake_code", "enter_code", "keypad", True,
            "The keypad accepted a code.", room)
        self.assertEqual(answer.speech, "")
        self.assertEqual(len(model.reactions), 2)
        diagnostic = self.store.trace_path("fake_code").read_text(encoding="utf-8")
        self.assertIn("outcome_speech_filtered", diagnostic)

    def test_knocks_are_firsthand_memory_not_newly_invented_recollection(self):
        room = world()
        room["heard_knocks"] = True
        room["lights_on"] = True
        model = LocalModel([goal("inspect", "maintenance_note")],
                           "That's a warning, all right.")
        agent = self.agent(model)
        agent.outcome("heard", "use", "breaker_box", True,
                      "Eli restored power. Three slow knocks sounded behind the door.",
                      room, speak=False)
        result = agent.decide("heard", "Check out that paper.", world(note=True) | {
            "heard_knocks": True, "lights_on": True,
        })
        self.assertEqual(result.actions[0]["target"], "maintenance_note")
        system = model.planned[0][0]["content"]
        self.assertIn('"you_actually_heard_knocks":true', system)
        self.assertIn("personally HEARD", system)

    def test_first_person_ending_reacts_to_escape_not_code_only(self):
        room = world()
        room["door_unlocked"] = True
        room["escaped"] = True
        room["heard_knocks"] = True
        room["actor_at"] = "exit_door"
        model = LocalModel([], "I opened it and stepped outside. I'm free, but what was knocking?")
        answer = self.agent(model).outcome(
            "ending", "use", "exit_door", True,
            "Eli opened the unlocked door and stepped out of camera view.",
            room)
        self.assertIn("stepped outside", answer.speech)
        self.assertIn("YOU JUST OPENED THE UNLOCKED DOOR", model.reactions[0][-1]["content"])
        self.assertEqual(len(model.reactions), 1)

    def test_reaction_is_brief_without_flattening_personality(self):
        room = world()
        room["lights_on"] = True
        lengthy = ("The breaker is on. The lights came back. "
                   "That's good, although I am worried. "
                   "I keep thinking about every shadow. "
                   "I could talk about this room forever.")
        text = Agent._ground_verified_outcome(
            lengthy, "use", "breaker_box", True, "The breaker is on.", room)
        self.assertIn("I am worried", text)
        self.assertNotIn("every shadow", text)

    def test_held_flashlight_cannot_also_be_on_the_desk(self):
        room = world()
        room["inventory"] = ["flashlight"]
        room["flashlight_on"] = True
        original = "On the desk, the flashlight is now in my hand."
        corrected = Agent._correct_room_perspective(original, room, {"facts": []})
        self.assertEqual(corrected, "The flashlight is in my hand.")


if __name__ == "__main__":
    unittest.main()
