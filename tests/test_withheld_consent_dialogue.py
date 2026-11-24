"""Guard against an untrusting Eli promising an action he did not consent to.

These tests exercise the same production single-pass goal planner contract.
They verify that spoken commitments never outrun the engine-authorized queue.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from test_relationship_action_gate import TestModel, appraisal, goal, plan
from test_semantic_planner import world

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


class WithheldConsentDialogue(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = SessionStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, model):
        return Agent(model, self.store, PERSONA)

    def test_declined_goal_cannot_speak_a_false_future_promise(self):
        model = TestModel(
            plan([goal("use", "breaker_box")],
                 speech="Fine. I'll flip the breaker now.",
                 social=appraisal(willingness="decline", motive="none")),
            spoken="No. I'm not doing that on your orders. Tell me why.")
        result = self.agent(model).decide("declined", "Flip the breaker.", world())
        self.assertEqual(result.action, "wait")
        self.assertEqual(result.actions, ())
        self.assertIn("not doing that", result.speech)
        self.assertNotIn("I'll flip", result.speech)
        self.assertEqual(len(model.planner_calls), 1)
        self.assertEqual(len(model.converse_calls), 1)
        records = [json.loads(line) for line in
                   self.store.trace_path("declined").read_text().splitlines()]
        gate = next(row for row in records
                    if row["kind"] == "relationship_action_gate")
        self.assertEqual(gate["details"]["decision"], "withheld_consent")
        self.assertEqual(gate["details"]["model_willingness"], "decline")
        self.assertEqual(gate["details"]["blocked_model_goals"],
                         [goal("use", "breaker_box")])

    def test_consideration_preserves_natural_hesitation_without_extra_call(self):
        model = TestModel(
            plan([goal("use", "breaker_box")],
                 speech="I need a moment. Why should I trust you?",
                 social=appraisal(willingness="consider")),
            spoken="I need to think this over.")
        result = self.agent(model).decide("consider", "Could you try the breaker?", world())
        self.assertEqual(result.action, "wait")
        self.assertFalse(result.actions)
        self.assertIn("Why should I trust you", result.speech)
        self.assertEqual(len(model.planner_calls), 1)
        self.assertFalse(model.converse_calls)

    def test_failed_refusal_rewrite_never_restores_an_action_promise(self):
        model = TestModel(
            plan([goal("use", "breaker_box")],
                 speech="I'm going to switch on that breaker.",
                 social=appraisal(willingness="decline")),
            spoken="Okay, I'll do it now.")
        result = self.agent(model).decide("bad_rewrite", "Switch it on.", world())
        self.assertFalse(result.actions)
        self.assertEqual(result.action, "wait")
        self.assertFalse(result.speech)
        self.assertIn("not agreed", result.status)
        self.assertEqual(len(model.planner_calls), 1)
        self.assertEqual(len(model.converse_calls), 2)
        history = self.store.load("bad_rewrite")["history"]
        self.assertFalse(any("I'll do it" in row["content"] for row in history))

    def test_future_thought_is_not_a_physical_commitment(self):
        agent = self.agent(TestModel({}))
        self.assertFalse(agent._unperformed_action_commitment("I'll think about it."))
        self.assertFalse(agent._unperformed_action_commitment(
            "I won't touch that breaker until you explain."))
        self.assertTrue(agent._unperformed_action_commitment(
            "Fine, I'm doing it now."))
        self.assertTrue(agent._unperformed_action_commitment(
            "Let me check the door."))
        self.assertTrue(agent._unperformed_action_commitment(
            "I can turn on the flashlight."))

    def test_plain_conversation_stays_single_pass(self):
        model = TestModel({
            "kind": "conversation", "goals": [],
            "speech": "You haven't earned my trust. Just talk.",
            "emotion": "suspicious",
            "appraisal": appraisal(willingness="decline", purpose="just_talking"),
        }, spoken="No.")
        result = self.agent(model).decide("chat", "I only want to talk.", world())
        self.assertEqual(result.action, "wait")
        self.assertIn("Just talk", result.speech)
        self.assertFalse(model.converse_calls)


if __name__ == "__main__":
    unittest.main()
