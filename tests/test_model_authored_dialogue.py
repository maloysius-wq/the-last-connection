"""Production local GGUF owns Eli's dialogue, not fixed bridge messages.

World state/action authorization remains Godot's; conversational generation
is never a second opportunity to issue physical commands.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, BackendUnavailable, SessionStore
from test_semantic_planner import proposed, step, world

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


class HumanBackend:
    def __init__(self, intent=None, replies=(), audit=None):
        self.intent = intent or proposed("conversation", speech="I don't know.")
        self.replies = list(replies)
        self.audit = audit
        self.spoken_prompts = []
        self.interpreted = 0
        self.reviewed = 0

    def interpret(self, messages):
        self.interpreted += 1
        return self.intent

    def review(self, messages):
        self.reviewed += 1
        return self.audit or {"kind": "clarify", "steps": [], "reason": "uncertain"}

    def converse(self, messages):
        self.spoken_prompts.append(messages)
        return self.replies.pop(0) if self.replies else "No, that doesn't make sense to me."


class TestModelAuthoredDialogue(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def agent(self, backend):
        return Agent(backend, self.store, PERSONA)

    def test_valid_action_uses_model_line_not_fixed_plan_phrase(self):
        backend = HumanBackend(proposed("action", [
            step("use", "breaker_box", "flip the breaker")
        ], speech="Okay, I'll flip the breaker. I really hope this doesn't make things worse."))
        result = self.agent(backend).decide("plan", "Please flip the breaker.", world())
        self.assertEqual((result.action, result.target), ("use", "breaker_box"))
        self.assertEqual(result.speech,
                         "Okay, I'll flip the breaker. I really hope this doesn't make things worse.")
        self.assertEqual(len(backend.spoken_prompts), 0)

    def test_rejected_model_step_gets_specific_human_explanation(self):
        backend = HumanBackend(proposed("action", [
            step("use", "breaker_box", "activate invisible control")
        ], speech="I'm not completely sure which actions you mean."),
            ["I can see the breaker on the wall, but I don't know which control you're referring to. "
             "Do you want me to try its lever?"])
        result = self.agent(backend).decide("unclear", "Try the invisible control.", world())
        self.assertEqual(result.action, "wait")
        self.assertEqual(result.actions, ())
        self.assertIn("breaker", result.speech)
        self.assertNotIn("which actions", result.speech)
        self.assertEqual(len(backend.spoken_prompts), 1)
        self.assertIn("The interpretation", backend.spoken_prompts[0][-1]["content"] if False
                      else backend.spoken_prompts[0][0]["content"])

    def test_model_conversation_clarification_without_canned_line(self):
        backend = HumanBackend(proposed("clarify", [], "Could you say that again?"),
            ["Are you asking me to look behind that door? I can't see what's there from here."])
        result = self.agent(backend).decide("chat", "Do that thing over there?", world())
        self.assertEqual(result.action, "wait")
        self.assertIn("look behind that door", result.speech)
        self.assertNotIn("say that again", result.speech.lower())

    def test_model_response_can_be_empty_without_fake_eli_statement(self):
        backend = HumanBackend(proposed("action", [
            step("take", "flashlight", "take the flashlight")
        ], speech="I already grabbed the flashlight."),
            ["I picked it up already.", "I switched on the lights."])
        result = self.agent(backend).decide("guard", "Take the flashlight.", world())
        self.assertEqual(result.action, "take")
        self.assertEqual(result.speech, "")
        self.assertEqual(len(backend.spoken_prompts), 2)

    def test_successful_outcome_is_model_authored_and_grounded(self):
        backend = HumanBackend(replies=[
            "Jesus, those lights just came on. Did you hear three knocks behind the door?"
        ])
        agent = self.agent(backend)
        room = world()
        room.update(lights_on=True, heard_knocks=True)
        message = ("Eli flipped the breaker up. Power was restored, the overhead "
                   "lights switched on, and three knocks came from the locked door.")
        reply = agent.outcome("outcome", "use", "breaker_box", True, message, room)
        self.assertIn("Jesus", reply.speech)
        self.assertIn("three knocks", reply.speech)
        self.assertEqual(len(backend.spoken_prompts), 1)
        stored = self.store.load("outcome")
        self.assertEqual(stored["facts"][-1]["description"], message)
        self.assertIn("Jesus", stored["history"][-1]["content"])

    def test_no_llm_inference_after_intermediate_queued_steps(self):
        backend = HumanBackend()
        reply = self.agent(backend).outcome(
            "queue", "take", "flashlight", True, "Eli picked up the flashlight.",
            world(), speak=False)
        self.assertEqual(reply.speech, "")
        self.assertEqual(len(backend.spoken_prompts), 0)
        self.assertEqual(len(self.store.load("queue")["facts"]), 1)

    def test_unverified_puzzle_secret_is_suppressed_but_event_is_recorded(self):
        backend = HumanBackend(replies=[
            "I just entered 4317 and opened the door!", "I just opened it!"
        ])
        reply = self.agent(backend).outcome(
            "rejected", "use", "breaker_box", False,
            "The breaker did not respond.", world())
        self.assertEqual(reply.speech, "")
        self.assertEqual(len(self.store.load("rejected")["facts"]), 1)

    def test_model_backend_failure_never_disguises_itself_as_eli(self):
        class FailingBackend(HumanBackend):
            def converse(self, messages):
                raise BackendUnavailable("Model couldn't speak")
        reply = self.agent(FailingBackend()).outcome(
            "failed-model", "inspect", "breaker_box", True,
            "Eli inspected the lever without moving it.", world())
        self.assertEqual(reply.speech, "")
        self.assertEqual(len(self.store.load("failed-model")["facts"]), 1)

    def test_outcome_response_cannot_create_new_actions(self):
        backend = HumanBackend(replies=[
            "I can see the switch moved. I'm scared to touch anything else."
        ])
        reply = self.agent(backend).outcome(
            "observe", "use", "breaker_box", True,
            "Eli flipped the breaker.", world())
        self.assertEqual(reply.action, "wait")
        self.assertEqual(reply.actions, ())


if __name__ == "__main__":
    unittest.main()
