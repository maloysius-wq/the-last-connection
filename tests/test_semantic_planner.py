"""One-call natural-language semantic planning with strict world authority.

No phrase dictionary is needed for real GGUF decisions. These tests inject
semantic interpretations as a model would produce, including unfamiliar
paraphrases, mixed chat and commands, pronouns, hypotheticals and attacks.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ai_bridge.agent import Agent, LlamaCppBackend, OllamaBackend, SessionStore
from ai_bridge.semantic import validated_steps, PlanRejected

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


def world(*, note=False):
    objects = {
        "flashlight": {"visible": True, "can_take": True,
                       "description": "Metal flashlight by the desk."},
        "breaker_box": {"visible": True, "description": "Breaker switch on the wall."},
        "exit_door": {"visible": True, "description": "A locked door."},
        "keypad": {"visible": True, "description": "A four-digit keypad."},
    }
    if note:
        objects["maintenance_note"] = {"visible": True, "description": "A folded note."}
    return {"room": "maintenance_chamber", "actor_at": "room_center",
            "objects": objects, "inventory": [], "lights_on": False,
            "flashlight_on": False, "door_unlocked": False, "last_observation": ""}


def step(action, target, evidence, argument=""):
    return {"action": action, "target": target, "argument": argument,
            "evidence": evidence}


def proposed(kind, steps=(), speech="Wait, you want me to try that?"):
    return {"kind": kind, "steps": list(steps),
            "speech": speech, "emotion": "afraid"}


class SemanticBackend:
    def __init__(self, response):
        self.response = response
        self.calls = []
    def interpret(self, messages):
        self.calls.append(messages)
        return self.response
    def respond(self, messages):
        raise AssertionError("Should not fall back to old single-action parser")
    def converse(self, messages):
        raise AssertionError("Single semantic inference covers conversation")


class SemanticPlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = SessionStore(Path(self.tmp.name))
    def tearDown(self):
        self.tmp.cleanup()
    def decide(self, user, response, *, state=None, room=None):
        backend = SemanticBackend(response)
        agent = Agent(backend, self.store, PERSONA)
        if state is not None:
            self.store.save("player", state)
        decision = agent.decide("player", user, room or world())
        self.assertEqual(len(backend.calls), 1)
        self.assertIn("SEMANTIC ACTION INTERPRETATION", backend.calls[0][0]["content"])
        self.assertEqual(backend.calls[0][-1]["content"], user)
        return decision

    def test_real_screenshot_full_sequence_needs_no_phrase_parser(self):
        text = ("I see what's on the screen, and I see the flashlight. "
                "Go ahead and go grab it, turn it on, and take a look around "
                "the room, then tell me what you see.")
        response = proposed("action", [
            step("take", "flashlight", "go grab it"),
            step("use", "flashlight", "turn it on", "on"),
            step("survey", "room", "take a look around the room"),
        ])
        result = self.decide(text, response)
        self.assertEqual([(s["action"], s["target"]) for s in result.actions],
                         [("take", "flashlight"), ("use", "flashlight"), ("survey", "room")])
        self.assertEqual(result.action, "take")
        self.assertIn("look around the room", result.speech)
        self.assertNotIn("actually picked", result.speech)

    def test_unfamiliar_natural_wording_no_new_regex_needed(self):
        text = "Any chance you could make your way to the electrical panel and examine it?"
        steps = [step("move_to", "breaker_box", "make your way to the electrical panel"),
                 step("inspect", "breaker_box", "examine it")]
        result = self.decide(text, proposed("action", steps))
        self.assertEqual(len(result.actions), 2)
        self.assertEqual(result.actions[0]["target"], "breaker_box")

    def test_conversation_can_mention_actions_without_triggering_them(self):
        result = self.decide(
            "Wouldn't it be frightening if you opened that door?",
            proposed("conversation", speech="Yeah. I don't trust what's behind it."))
        self.assertEqual(result.action, "wait")
        self.assertEqual(result.actions, ())
        self.assertIn("don't trust", result.speech)

    def test_chat_and_commands_in_same_turn(self):
        text = "I'm worried too. Please switch on the flashlight and look around."
        result = self.decide(text, proposed("action", [
            step("use", "flashlight", "switch on the flashlight", "on"),
            step("survey", "room", "look around")]))
        self.assertEqual([s["action"] for s in result.actions], ["use", "survey"])

    def test_ambiguous_request_asks_before_acting(self):
        result = self.decide("Can you check that thing?", proposed(
            "clarify", speech="Which thing? The keypad or the switch?"))
        self.assertEqual(result.action, "wait")
        self.assertIn("Which thing", result.speech)

    def test_model_cannot_create_steps_after_current_user_request(self):
        result = self.decide("Pick up the flashlight.",
                             proposed("action", [
                                 step("take", "flashlight", "Pick up the flashlight"),
                                 step("use", "flashlight", "turn it on", "on")]))
        self.assertEqual(result.action, "wait")
        self.assertEqual(result.actions, ())

    def test_model_cannot_reuse_same_quote_for_two_actions(self):
        result = self.decide("Pick up the flashlight.", proposed("action", [
            step("take", "flashlight", "Pick up the flashlight"),
            step("use", "flashlight", "Pick up the flashlight")]))
        self.assertEqual(result.action, "wait")

    def test_model_cannot_pick_up_door(self):
        result = self.decide("Bring that door over here.",
                             proposed("action", [step("take", "exit_door", "Bring that door over here")]))
        self.assertEqual(result.action, "wait")

    def test_unseen_note_cannot_be_read_without_breaker(self):
        result = self.decide("Read the folded paper.", proposed(
            "action", [step("inspect", "maintenance_note", "Read the folded paper")]))
        self.assertEqual(result.action, "wait")

    def test_breaker_can_reveal_note_later_in_same_plan(self):
        result = self.decide("Turn on the breaker, then read the note.", proposed("action", [
            step("use", "breaker_box", "Turn on the breaker"),
            step("inspect", "maintenance_note", "read the note"),
        ]))
        self.assertEqual([s["target"] for s in result.actions],
                         ["breaker_box", "maintenance_note"])

    def test_never_infer_keypad_code_from_world_or_model(self):
        result = self.decide("Try the keypad.", proposed(
            "action", [step("enter_code", "keypad", "Try the keypad", "4317")]))
        self.assertEqual(result.action, "wait")

    def test_explicit_keypad_code_is_allowed(self):
        result = self.decide("Punch 4317 into the keypad.", proposed(
            "action", [step("enter_code", "keypad", "Punch 4317 into the keypad", "4317")]))
        self.assertEqual((result.action, result.target, result.argument),
                         ("enter_code", "keypad", "4317"))

    def test_negated_command_not_executable_even_if_model_misunderstands(self):
        result = self.decide("Don't touch the breaker.", proposed(
            "action", [step("use", "breaker_box", "touch the breaker")]))
        self.assertEqual(result.action, "wait")

    def test_hypothetical_not_executable_even_if_model_misunderstands(self):
        result = self.decide("What if you grab the flashlight?", proposed(
            "action", [step("take", "flashlight", "grab the flashlight")]))
        self.assertEqual(result.action, "wait")

    def test_prior_turn_does_not_authorize_new_action(self):
        self.decide("How are you feeling?", proposed(
            "action", [step("use", "flashlight", "turn it on", "on")]),
            state={"history": [{"role": "user", "content": "Turn it on."}], "facts": []})

    def test_ambiguous_multi_target_pronoun_rejected(self):
        text = "There is a flashlight and a keypad. Go use it."
        result = self.decide(text, proposed("action", [
            step("use", "flashlight", "Go use it")]))
        self.assertEqual(result.action, "wait")

    def test_earlier_referent_can_resolve_clear_follow_up(self):
        result = self.decide("Switch it on.", proposed("action", [
            step("use", "flashlight", "Switch it on", "on")]),
            state={"history": [], "facts": [], "referent": "flashlight"})
        self.assertEqual(result.target, "flashlight")

    def test_proposed_conversation_with_steps_fails_closed(self):
        result = self.decide("Are you safe?", proposed(
            "conversation", [step("take", "flashlight", "grab it")]))
        self.assertEqual(result.action, "wait")
        self.assertEqual(result.actions, ())

    def test_malformed_model_output_never_triggers_physical_action(self):
        result = self.decide("Pick it up.", {"kind": "action", "speech": "Sure.",
                                             "steps": "take", "emotion": "calm"})
        self.assertEqual(result.action, "wait")


class BackendContractTests(unittest.TestCase):
    def test_llamacpp_one_structured_call_for_dialogue_and_actions(self):
        calls = []
        class Reply:
            def __init__(self, payload):
                self.data = json.dumps(payload).encode()
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n): return self.data

        output = proposed("conversation", speech="I don't trust that door.")
        def fetch(req, timeout):
            calls.append((json.loads(req.data), timeout))
            return Reply({"choices": [{"message": {"content": json.dumps(output)}}]})
        with patch("ai_bridge.agent.request.urlopen", side_effect=fetch):
            reply = LlamaCppBackend().interpret([{"role": "user", "content": "Hello"}])
        self.assertEqual(reply, output)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0]["response_format"]["type"], "json_schema")
        self.assertIn("steps", calls[0][0]["response_format"]["schema"]["properties"])
        self.assertEqual(calls[0][0]["stream"], False)

    def test_ollama_interpret_uses_same_schema(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n):
                return json.dumps({"message": {"content": json.dumps(
                    proposed("conversation", speech="I'm here."))}}).encode()
        sent = []
        def fetch(req, timeout):
            sent.append(json.loads(req.data))
            return Reply()
        with patch("ai_bridge.agent.request.urlopen", side_effect=fetch):
            reply = OllamaBackend().interpret([{"role": "user", "content": "Hi"}])
        self.assertEqual(reply["steps"], [])
        self.assertIn("steps", sent[0]["format"]["properties"])


if __name__ == "__main__":
    unittest.main()
