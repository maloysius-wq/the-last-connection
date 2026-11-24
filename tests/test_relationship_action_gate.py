"""Regression of uploaded eli_1795537220_5153 from Nov 24 2026.

The user's model repeatedly returned action/willingness=accept even at
trust=-100, anger=100. The engine must translate emotional state into
physical agency, not merely display the anger label next to blind obedience.
One GGUF planner call remains authoritative about requested goals, while the
rare pushback is another DIALOGUE call with no action-authorizing power.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from test_semantic_planner import world

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


def goal(action, target, argument=""):
    return {"action": action, "target": target, "argument": argument}


def appraisal(*, trust=0, anger=0, stress=0, willingness="accept",
              motive="none", boundary="", purpose="requesting_action"):
    return {"trust": trust, "anger": anger, "stress": stress,
            "willingness": willingness, "action_motive": motive,
            "boundary_update": boundary, "claimed_purpose": purpose}


def plan(goals, *, emotion="angry", motive="none",
         speech="I'll turn on the breaker box.", social=None):
    return {"kind": "action", "goals": goals, "emotion": emotion,
            "speech": speech, "appraisal": social or appraisal(motive=motive)}


class TestModel:
    def __init__(self, response, spoken="No. I'm not going to do that just because you told me to."):
        self.response = response
        self.spoken = spoken
        self.planner_calls = []
        self.converse_calls = []

    def plan_goals(self, messages):
        self.planner_calls.append(messages)
        return self.response

    def converse(self, messages):
        self.converse_calls.append(messages)
        return self.spoken


class RelationshipAgency(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = SessionStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, name, model, *, trust=-40, anger=24, stress=74,
              history=None, facts=None, boundaries=None):
        self.store.save(name, {
            "history": history or [], "facts": facts or [],
            "relationship": {
                "trust": trust, "anger": anger, "stress": stress, "turns": 7,
                "claimed_purpose": "requesting_action",
                "boundaries": boundaries or [],
            },
        })
        return Agent(model, self.store, PERSONA)

    def test_exact_exported_extreme_anger_blocks_a_blindly_accepted_breaker_command(self):
        model = TestModel(plan([
            goal("use", "breaker_box"),
            goal("inspect", "maintenance_note"),
        ], speech="I'll turn on the breaker and check the note.",
           motive="self_preservation"),
            spoken="No. You've spent the whole conversation taking the piss out of me. "
                   "I'm not going to be your errand boy.")
        agent = self.agent("angry", model, trust=-100, anger=100, stress=100,
                           boundaries=["No explicit boundaries set", "None set"])
        answer = agent.decide(
            "angry",
            "Go turn on the breaker box and then look at the paper.", world())
        self.assertEqual(answer.action, "wait")
        self.assertEqual(answer.actions, ())
        self.assertIn("errand boy", answer.speech)
        self.assertEqual(len(model.planner_calls), 1)
        self.assertEqual(len(model.converse_calls), 1)
        self.assertEqual(model.converse_calls[0][-1]["content"],
                         "Go turn on the breaker box and then look at the paper.")
        assert "CURRENT EMOTIONAL ACTION DECISION" in model.converse_calls[0][0]["content"]
        self.assertNotIn("No explicit boundaries set",
                         self.store.load("angry")["relationship"]["boundaries"])
        logs = self.store.trace_path("angry").read_text(encoding="utf-8")
        traces = [json.loads(line) for line in logs.splitlines()]
        gate = next(t for t in traces if t["kind"] == "relationship_action_gate")
        self.assertEqual(gate["details"]["decision"], "challenge")
        self.assertEqual(len(gate["details"]["blocked_goals"]), 2)
        self.assertEqual(gate["details"]["model_willingness"], "accept")

    def test_extreme_hostility_blocks_verified_keypad_and_exit_sequence(self):
        model = TestModel(plan([
            goal("enter_code", "keypad", "4317"), goal("use", "exit_door"),
        ], speech="I'll enter 4317 and leave.",
           motive="self_preservation"),
            spoken="I'm not following another order from you. I need to think.")
        agent = self.agent("code", model, trust=-95, anger=100,
                           stress=100, facts=[{
                               "action": "inspect", "target": "maintenance_note",
                               "success": True,
                               "description": "The maintenance note reads: RESET SEQUENCE 4317.",
                           }])
        scene = world(note=True)
        scene["lights_on"] = True
        response = agent.decide("code", "Put in that code and leave.", scene)
        self.assertFalse(response.actions)
        self.assertIn("need to think", response.speech)
        self.assertEqual(scene["door_unlocked"], False)

    def test_midrange_self_preservation_can_proceed_but_speech_is_independent(self):
        model = TestModel(plan([
            goal("take", "flashlight"), goal("use", "flashlight", "on"),
        ], motive="self_preservation", speech="I'll grab that and switch it on."),
            spoken="I'll turn on the flashlight so I can see better. "
                   "Don't mistake that for me trusting you.")
        # The actual uploaded fourth-turn post-appraisal state was
        # trust=-75, anger=69. That is tense enough to need an authentic
        # self-directed acknowledgment, without being too angry to act.
        agent = self.agent("own_choice", model, trust=-75, anger=69, stress=80)
        result = agent.decide("own_choice",
                              "Get that flashlight and turn it on.", world())
        self.assertEqual(result.actions, (
            goal("take", "flashlight"), goal("use", "flashlight", "on")))
        self.assertIn("Don't mistake", result.speech)
        self.assertEqual(len(model.planner_calls), 1)
        self.assertEqual(len(model.converse_calls), 1)
        traces = [json.loads(x) for x in self.store.trace_path(
            "own_choice").read_text().splitlines()]
        gate = next(t for t in traces if t["kind"] == "relationship_action_gate")
        self.assertEqual(gate["details"]["decision"], "allow")

    def test_high_tension_never_falls_back_to_obedient_speech_when_rewrite_fails(self):
        model = TestModel(plan([
            goal("take", "flashlight"), goal("use", "flashlight", "on"),
        ], motive="self_preservation", speech="I'll do whatever you say."),
            spoken="I already switched the flashlight on.")
        agent = self.agent("inconsistent_voice", model, trust=-75,
                           anger=69, stress=80)
        result = agent.decide("inconsistent_voice",
                              "Get that flashlight and turn it on.", world())
        self.assertEqual(result.actions, (
            goal("take", "flashlight"), goal("use", "flashlight", "on")))
        self.assertEqual(result.speech, "")
        self.assertEqual(len(model.converse_calls), 2)

    def test_hostility_refuses_obedience_even_before_anger_peaks(self):
        model = TestModel(plan([goal("use", "breaker_box")],
                               motive="obedience"),
                          spoken="Why would I jump when you say jump?")
        agent = self.agent("obey", model, trust=-78, anger=78, stress=94)
        response = agent.decide("obey", "Flip the breaker.", world())
        self.assertFalse(response.actions)
        self.assertIn("Why would I jump", response.speech)

    def test_trust_cools_enough_to_act_without_a_fixed_turn_count(self):
        model = TestModel(plan([goal("use", "breaker_box")],
                               motive="self_preservation",
                               speech="I'll turn on the breaker to get some light."),
                          spoken="I'll turn on that breaker so I can see.")
        agent = self.agent("cooled", model, trust=-85, anger=28, stress=75)
        response = agent.decide("cooled", "Try the breaker now.", world())
        self.assertEqual(response.actions, (goal("use", "breaker_box"),))
        self.assertEqual(len(model.planner_calls), 1)
        self.assertEqual(len(model.converse_calls), 0)

    def test_immediately_unlocked_exit_is_elis_independent_way_out(self):
        model = TestModel(plan([goal("use", "exit_door")],
                               motive="self_preservation",
                               speech="I'll open the door and get out."),
                          spoken="I'll open the door and get out of here. "
                                 "I'm doing it for myself, not for you.")
        agent = self.agent("exit", model, trust=-100, anger=100, stress=100)
        scene = world()
        scene["door_unlocked"] = True
        result = agent.decide("exit", "Go out through that door.", scene)
        self.assertEqual(result.actions, (goal("use", "exit_door"),))
        self.assertIn("for myself", result.speech)
        # Godot's separate unlocked-door confirmation still applies.

    def test_no_generic_acceptance_is_rendered_after_blocked_action(self):
        model = TestModel(plan([goal("use", "breaker_box")],
                               motive="obedience"),
                          spoken="I'll turn on the breaker for you.")
        agent = self.agent("unsafe_reply", model, trust=-100, anger=100)
        result = agent.decide("unsafe_reply", "Flip the breaker.", world())
        self.assertFalse(result.actions)
        self.assertNotIn("I'll turn on", result.speech)
        self.assertTrue(result.status)
        self.assertEqual(len(model.planner_calls), 1)
        self.assertEqual(len(model.converse_calls), 2)

    def test_placeholders_removed_from_legacy_saves(self):
        agent = self.agent("old", TestModel(plan([], speech="I don't know.")),
                           boundaries=["None set", "No explicit boundaries set",
                                       "Do not ask about my screen"])
        self.assertEqual(agent._relationship(
            self.store.load("old"))["boundaries"], ["Do not ask about my screen"])

    def test_placeholder_from_new_model_is_not_stored(self):
        agent = self.agent("placeholder", TestModel(plan(
            [], speech="I don't know.", social=appraisal(
                willingness="consider", boundary="No explicit boundaries set"))))
        agent.decide("placeholder", "Hi", world())
        self.assertEqual(self.store.load("placeholder")["relationship"]["boundaries"], [])


if __name__ == "__main__":
    unittest.main()
