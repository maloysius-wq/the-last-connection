"""Camera-room perspective and fresh-session playtest regressions.

The remote human uses a terminal. Eli alone is physically present with the
breaker, keypad, door and flashlight. The tests assert this is true both in
inference context and in the resulting dialogue.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore

ROOT = Path(__file__).resolve().parents[1]

def fresh_room():
    return {
        "room": "maintenance_chamber",
        "inventory": [],
        "actor_at": "room_center",
        "last_observation": "",
        "lights_on": False,
        "door_unlocked": False,
        "flashlight_on": False,
        "objects": {
            "flashlight": {"visible": True, "can_take": True,
                           "description": "A metal flashlight resting on a desk."},
            "breaker_box": {"visible": True, "can_take": False,
                            "description": "A breaker box on the wall; its lever is down."},
            "keypad": {"visible": True, "can_take": False,
                       "description": "A four-digit number pad by the door."},
            "exit_door": {"visible": True, "can_take": False,
                          "description": "A locked door on the back wall."},
        },
    }


class DialogueModel:
    def __init__(self, text):
        self.text = text
        self.inputs = []

    def converse(self, messages):
        self.inputs.append(messages)
        return self.text

    def respond(self, messages):
        raise AssertionError("A conversational message must not become a physical action request")


class TestFreshRoomPerspective(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = SessionStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, model):
        return Agent(model, self.store, ROOT / "data/characters/eli.json")

    def test_player_story_is_plain_user_text_and_world_is_eli_context(self):
        story = ("I just appeared here in this control room, noticed you on the "
                 "screen, and I've been instructed to help you escape. "
                 "I'm not sure how I got here.")
        model = DialogueModel("That is unsettling. I can see the breaker box from here.")
        result = self.agent(model).decide("first", story, fresh_room())
        self.assertEqual(result.action, "wait")
        self.assertEqual(model.inputs[0][-1], {"role": "user", "content": story})
        system = model.inputs[0][0]["content"]
        self.assertIn("you_are", system)
        self.assertIn("Eli physically INSIDE", system)
        self.assertIn('"speaker_can_reach_your_room":false', system)
        self.assertIn('"only_you_can_touch_room_objects":true', system)
        self.assertIn('"first_contact":true', system)
        self.assertIn('"door_previously_attempted":false', system)
        self.assertIn('"flashlight"', system)

    def test_exact_playtest_reply_is_corrected_without_second_inference(self):
        model = DialogueModel(
            "Oh, wow, so you just showed up? That's wild. "
            "The breaker box is off. The door on the back wall? Still locked. "
            "You've got a flashlight on the desk—can you grab that?"
        )
        result = self.agent(model).decide(
            "screen", "I appeared in this control room and I can see you on a screen.", fresh_room())
        self.assertEqual(result.action, "wait")
        self.assertEqual(len(model.inputs), 1)
        self.assertIn("There's a flashlight on the desk here", result.speech)
        self.assertIn("should I pick it up", result.speech)
        self.assertNotIn("Still locked", result.speech)
        self.assertIn("locked", result.speech)

    def test_fresh_session_is_not_an_old_session(self):
        model = DialogueModel("I can see a flashlight on my desk.")
        agent = self.agent(model)
        agent.decide("one", "Can you hear me?", fresh_room())
        agent.decide("two", "Who are you?", fresh_room())
        self.assertEqual(len(model.inputs), 2)
        for messages in model.inputs:
            self.assertIn('"first_contact":true', messages[0]["content"])
            self.assertIn('"door_previously_attempted":false', messages[0]["content"])
        self.assertEqual(model.inputs[1][-1]["content"], "Who are you?")
        self.assertNotIn("Can you hear me?", json.dumps(model.inputs[1]))

    def test_later_confirmed_attempt_can_say_still_locked(self):
        agent = self.agent(DialogueModel("The door is still locked."))
        agent.outcome("attempted", "use", "exit_door", False,
                      "The exit door is locked.", fresh_room())
        result = agent.decide("attempted", "What happened with the door?", fresh_room())
        self.assertIn("still locked", result.speech)
        # It is now justified, unlike when no attempt has happened.

    def test_no_automatic_hand_over_of_remote_operator_objects(self):
        agent = self.agent(DialogueModel(
            "You have a flashlight on your desk, could you pick it up?"
        ))
        result = agent.decide("operator", "What can I do from this control room?", fresh_room())
        self.assertIn("flashlight on the desk here", result.speech)
        self.assertIn("should I pick it up", result.speech)
        self.assertEqual(result.action, "wait")

    def test_personal_history_is_not_conflated_with_room_history(self):
        agent = self.agent(DialogueModel("I can't remember my childhood. It's unsettling."))
        result = agent.decide("memories", "What's your childhood like?", fresh_room())
        self.assertIn("childhood", result.speech)
        self.assertEqual(result.action, "wait")


if __name__ == "__main__":
    unittest.main()
