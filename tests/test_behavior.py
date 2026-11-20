"""Regression cases based on first real playtests: preserve conversation and intent."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, MockBackend, SessionStore
from ai_bridge.intent import classify

ROOT = Path(__file__).resolve().parents[1]

def world(*, inventory=(), lights=False, note=False):
    objects = {
        "flashlight": {"visible": True, "can_take": not bool(inventory),
                       "description": ("The flashlight is in Eli's inventory. It is off."
                                       if inventory else "A metal flashlight on the desk.")},
        "exit_door": {"visible": True, "can_take": False,
                      "description": "The exit door is locked."},
        "breaker_box": {"visible": True, "can_take": False,
                        "description": "A wall-mounted electrical breaker."},
        "keypad": {"visible": True, "can_take": False,
                   "description": "A four-digit keypad."},
    }
    if note:
        objects["maintenance_note"] = {"visible": True, "can_take": False,
                                       "description": "A folded note; writing must be examined."}
    return {"room": "maintenance_chamber", "inventory": list(inventory),
            "lights_on": lights, "flashlight_on": False,
            "objects": objects}

class CannedBackend:
    def __init__(self, reply):
        self.reply = reply
        self.messages = []
    def respond(self, messages):
        self.messages.append(messages)
        return dict(self.reply)

class TestIntent(unittest.TestCase):
    def test_personal_question_does_not_grant_motion(self):
        self.assertEqual(classify("Are you okay?").kind, "conversation")
        self.assertEqual(classify("What do you think about the door?").kind, "conversation")
        self.assertEqual(classify("What happens if you open the door?").kind, "conversation")
        self.assertEqual(classify("Could you tell me about the note?").kind, "conversation")

    def test_polite_action_is_not_confused_with_question(self):
        ask = classify("Could you turn on the flashlight?")
        self.assertEqual((ask.kind, ask.action, ask.target, ask.light_mode),
                         ("action", "use", "flashlight", "on"))
        request = classify("Can you pick up the flashlight?")
        self.assertEqual((request.action, request.target), ("take", "flashlight"))

    def test_flashlight_instructions_and_prerequisite(self):
        self.assertEqual((classify("Pick up the flashlight").action,
                          classify("Pick up the flashlight").target), ("take", "flashlight"))
        self.assertEqual((classify("Pick up the flashlight and turn it on").action,
                          classify("Pick up the flashlight and turn it on").light_mode),
                         ("use", "on"))
        self.assertEqual((classify("Switch the flashlight off").action,
                          classify("Switch the flashlight off").light_mode), ("use", "off"))

    def test_explicit_targets_not_unrelated_surfaces(self):
        ask = classify("Inspect the note")
        self.assertEqual((ask.kind, ask.action, ask.target),
                         ("action", "inspect", "maintenance_note"))
        ask = classify("Open the door")
        self.assertEqual((ask.kind, ask.action, ask.target),
                         ("action", "use", "exit_door"))

    def test_unclear_or_negated_instruction_does_not_authorize(self):
        for message in ("Go over there", "Don't pick up the flashlight",
                        "Would it help if you used the flashlight?",
                        "Tell me what you see", "Check something"):
            with self.subTest(message=message):
                self.assertEqual(classify(message).kind, "conversation")

    def test_pronoun_reference_to_known_focus(self):
        i = classify("Turn it on", focus="flashlight")
        self.assertEqual((i.action, i.target, i.light_mode),
                         ("use", "flashlight", "on"))
        self.assertEqual(classify("Turn it on").kind, "conversation")

    def test_entering_code_still_requires_clear_digits(self):
        i = classify("Enter 4317 on the keypad")
        self.assertEqual((i.action, i.target), ("enter_code", "keypad"))


class TestConversationGrounding(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))
    def tearDown(self):
        self.temp.cleanup()
    def agent(self, response):
        backend = CannedBackend(response)
        return Agent(backend, self.store, ROOT / "data/characters/eli.json"), backend

    def test_question_blocks_random_walk_without_losing_answer(self):
        agent, backend = self.agent({"speech": "I honestly don't know why I'm here. I remember a ringing phone.",
                                     "action": "move_to", "target": "exit_door",
                                     "emotion": "afraid", "argument": ""})
        reply = agent.decide("q1", "Why are you trapped here?", world())
        self.assertEqual(reply.action, "wait")
        self.assertIn("don't know", reply.speech)
        self.assertEqual(len(backend.messages), 1)

    def test_question_about_door_blocks_random_inspection(self):
        agent, _ = self.agent({"speech": "The door looks locked from here.",
                               "action": "inspect", "target": "exit_door"})
        reply = agent.decide("q2", "Is the door locked?", world())
        self.assertEqual(reply.action, "wait")
        self.assertIn("locked", reply.speech)

    def test_explicit_flashlight_request_corrects_wrong_target(self):
        agent, _ = self.agent({"speech": "I'm going to check the door.",
                               "action": "inspect", "target": "exit_door"})
        reply = agent.decide("a1", "Turn on the flashlight", world())
        self.assertEqual((reply.action, reply.target, reply.argument),
                         ("use", "flashlight", "on"))
        self.assertIn("flashlight", reply.speech.lower())

    def test_flashlight_goal_survives_model_misreading_missing_pickup(self):
        agent, backend = self.agent({
            "speech": "I can't use it because I haven't picked it up.",
            "action": "wait", "target": ""})
        reply = agent.decide("a1b", "Please turn on the flashlight", world())
        self.assertEqual((reply.action, reply.target, reply.argument),
                         ("use", "flashlight", "on"))
        self.assertIn("pick up", reply.speech)
        self.assertEqual(len(backend.messages), 1)

    def test_request_pickup_is_not_replaced_with_inspection(self):
        agent, _ = self.agent({"speech": "I'll look at it first.",
                               "action": "inspect", "target": "flashlight"})
        reply = agent.decide("a2", "Pick up the flashlight", world())
        self.assertEqual((reply.action, reply.target), ("take", "flashlight"))

    def test_unseen_note_never_becomes_an_allowed_action(self):
        agent, _ = self.agent({"speech": "I'll read that note.",
                               "action": "inspect", "target": "maintenance_note"})
        reply = agent.decide("a3", "Read the note", world(note=False))
        self.assertEqual(reply.action, "wait")
        self.assertIn("can't see", reply.speech)

    def test_no_code_is_invented_for_keypad(self):
        agent, _ = self.agent({"speech": "I'll enter 4317.", "action": "enter_code",
                               "target": "keypad", "argument": "4317"})
        reply = agent.decide("a4", "Enter the code on the keypad", world())
        self.assertEqual(reply.action, "wait")
        self.assertIn("four digits", reply.speech)

    def test_request_with_explicit_digits_keeps_authorization(self):
        agent, _ = self.agent({"speech": "Trying it.", "action": "enter_code",
                               "target": "keypad", "argument": "0000"})
        reply = agent.decide("a5", "Enter 4317 on the keypad", world())
        self.assertEqual((reply.action, reply.target, reply.argument),
                         ("enter_code", "keypad", "4317"))

    def test_actions_from_previous_turn_are_not_authorization(self):
        agent, _ = self.agent({"speech": "I could look for a note.",
                               "action": "inspect", "target": "maintenance_note"})
        reply = agent.decide("a6", "How are you feeling?", world(note=True))
        self.assertEqual(reply.action, "wait")

    def test_false_flashlight_outcome_explains_actual_prerequisite(self):
        agent = Agent(MockBackend(), self.store, ROOT / "data/characters/eli.json")
        reply = agent.outcome("a7", "use", "flashlight", False,
                              "It didn't work.", world())
        self.assertIn("desk", reply.speech)
        self.assertIn("pick it up", reply.speech)

    def test_pickup_and_switch_on_feedback_without_llm_second_pass(self):
        backend = CannedBackend({"speech": "Okay.", "action": "use",
                                 "target": "flashlight"})
        agent = Agent(backend, self.store, ROOT / "data/characters/eli.json")
        decision = agent.decide("a8", "Turn on the flashlight", world())
        self.assertEqual(decision.argument, "on")
        after = world(inventory=("flashlight",))
        after["flashlight_on"] = True
        result = agent.outcome("a8", "use", "flashlight", True,
                               "Eli picked up the flashlight from the desk and switched it on.", after)
        self.assertIn("see a little better", result.speech)
        self.assertEqual(len(backend.messages), 1)

    def test_conversation_context_contains_plain_speech_not_json_actions(self):
        agent, backend = self.agent({"speech": "The door looks heavy.",
                                     "action": "wait", "target": ""})
        agent.decide("q3", "What does the door look like?", world())
        agent.decide("q3", "What else can you see?", world())
        second = json.dumps(backend.messages[-1])
        self.assertIn("The door looks heavy.", second)
        self.assertNotIn('\"action\": \"wait\"', second)

if __name__ == "__main__":
    unittest.main()
