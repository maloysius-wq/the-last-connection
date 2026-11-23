"""The PRODUCTION goal pipeline replaces quote-matching two-pass actions.

Tests describe engine capabilities and desired end states, not keyword-specific
regex exemptions. None need a real GGUF to prove that a structured goal
reaches Godot without a second model veto.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from ai_bridge.agent import Agent, LlamaCppBackend, OllamaBackend, SessionStore
from ai_bridge.goals import GOAL_SCHEMA, GoalRejected, validate_goals, observed_code
from test_semantic_planner import world

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


def goal(action, target, argument=""):
    return {"action": action, "target": target, "argument": argument}


def raw_plan(goals, *, speech="I'll do what I can.", kind="action"):
    return {"kind": kind, "speech": speech, "emotion": "cautious",
            "goals": goals}


NOTE_FACT = {"action": "inspect", "target": "maintenance_note", "success": True,
             "description": "The maintenance note reads: 'RESET SEQUENCE 4317'."}


class GoalModel:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def plan_goals(self, messages):
        self.calls += 1
        self.messages = messages
        return self.response

    def review(self, messages):
        raise AssertionError("No second-model action veto in production")

    def interpret(self, messages):
        raise AssertionError("Legacy quote-based planner was invoked")

    def converse(self, messages):
        raise AssertionError("No extra pre-action speech inference")


class GoalPipeline(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.store = SessionStore(Path(self.directory.name))

    def tearDown(self):
        self.directory.cleanup()

    def decide(self, text, goals, *, facts=None, state=None, kind="action",
               speech="I'll try that.", room=None):
        self.store.save("test_goal", {"facts": facts or [], "history": [], **(state or {})})
        model = GoalModel(raw_plan(goals, speech=speech, kind=kind))
        agent = Agent(model, self.store, PERSONA)
        decision = agent.decide("test_goal", text, room or world())
        self.assertEqual(model.calls, 1)
        self.assertIn("YOU ARE ELI", model.messages[0]["content"])
        self.assertNotIn("ACTION COMPLETENESS AUDITOR", model.messages[0]["content"])
        self.assertNotIn("CONTIGUOUS quotation", model.messages[0]["content"])
        return decision

    def test_complete_goals_are_executed_without_quotes_or_review(self):
        message = ("Pick up the flashlight, turn it on, then go over to the "
                   "breaker box and turn that on as well.")
        answer = self.decide(message, [
            goal("take", "flashlight"), goal("use", "flashlight", "on"),
            goal("move_to", "breaker_box"), goal("use", "breaker_box")])
        self.assertEqual(answer.actions, (
            goal("take", "flashlight"), goal("use", "flashlight", "on"),
            goal("use", "breaker_box")))
        self.assertEqual(answer.status, "")

    def test_short_goal_lets_engine_approach_the_door(self):
        decision = self.decide("Could you try opening the door now?",
                               [goal("use", "exit_door", "open")])
        self.assertEqual(decision.actions, (goal("use", "exit_door"),))

    def test_single_flashlight_use_auto_picks_up_by_engine_contract(self):
        decision = self.decide("Get the flashlight lit.",
                               [goal("use", "flashlight", "on")])
        self.assertEqual(decision.actions, (goal("use", "flashlight", "on"),))

    def test_discovered_code_is_bound_to_observation_not_model_prose(self):
        room = world(note=True)
        answer = self.decide(
            "Use the sequence you read to unlock the door.",
            [goal("enter_code", "keypad", "known")],
            facts=[NOTE_FACT], room=room)
        self.assertEqual(answer.actions, (goal("enter_code", "keypad", "4317"),))
        self.assertEqual(observed_code([NOTE_FACT]), "4317")

    def test_unseen_code_rejects_without_invoking_second_inference(self):
        answer = self.decide("Enter the code.",
                             [goal("enter_code", "keypad", "4317")])
        self.assertEqual(answer.actions, ())
        self.assertTrue(answer.status.startswith("Goal not executed:"))
        self.assertFalse(answer.speech)

    def test_model_cannot_invent_different_four_digit_solution(self):
        answer = self.decide("Enter the known code.",
                             [goal("enter_code", "keypad", "9999")],
                             facts=[NOTE_FACT], room=world(note=True))
        self.assertEqual(answer.actions, ())
        self.assertIn("never provided", answer.status)

    def test_explicit_digits_override_known_context(self):
        answer = self.decide("Try entering 9876 on the keypad.",
                            [goal("enter_code", "keypad", "9876")],
                            facts=[NOTE_FACT], room=world(note=True))
        self.assertEqual(answer.actions, (goal("enter_code", "keypad", "9876"),))

    def test_hidden_note_visible_after_breaker_power_goal(self):
        answer = self.decide("Turn on the power and read the note.",
                            [goal("use", "breaker_box"),
                             goal("inspect", "maintenance_note")])
        self.assertEqual(answer.actions[-1], goal("inspect", "maintenance_note"))

    def test_conversation_never_executes_physical_goals(self):
        for text in ("What happens if you open the door?",
                     "Don't open the door, tell me how it works.",
                     "I can see the keypad from here."):
            with self.subTest(text=text):
                decision = self.decide(text, [], kind="conversation",
                                       speech="I'm not sure what's behind it.")
                self.assertEqual(decision.actions, ())
                self.assertEqual(decision.action, "wait")

    def test_kind_conversation_with_hidden_physical_goals_rejected(self):
        decision = self.decide("The door looks frightening.",
                               [goal("use", "exit_door")], kind="conversation")
        self.assertFalse(decision.actions)
        self.assertNotEqual(decision.status, "")

    def test_no_partial_execution_when_one_goal_invalid(self):
        decision = self.decide("Turn on the flashlight and unlock with a code.",
                               [goal("use", "flashlight", "on"),
                                goal("enter_code", "keypad", "9999")])
        self.assertEqual(decision.actions, ())
        self.assertNotEqual(decision.status, "")

    def test_engine_capability_map_is_target_and_operation_based(self):
        with self.assertRaises(GoalRejected):
            validate_goals([goal("take", "breaker_box")], world(), "Take it", [])
        with self.assertRaises(GoalRejected):
            validate_goals([goal("use", "ceiling")], world(), "Try it", [])
        scene = world()
        scene["objects"]["wall"] = {"visible": True, "description": "Heavy wall."}
        result = validate_goals([goal("experiment", "wall", "knock three times")],
                                scene, "Let's make some noise", [])
        self.assertEqual(result[0], goal("experiment", "wall", "knock three times"))

    def test_repeated_actions_collapse_without_quote_matching(self):
        plan = [goal("take", "flashlight"), goal("take", "flashlight")]
        self.assertEqual(validate_goals(plan, world(), "Pick up the flashlight", []),
                         (goal("take", "flashlight"),))

    def test_goal_diagnostics_record_one_inference_and_final_plan(self):
        self.decide("Turn on room power.", [goal("use", "breaker_box")])
        trace = self.store.trace_path("test_goal").read_text(encoding="utf-8")
        records = [json.loads(line) for line in trace.splitlines()]
        names = [record["kind"] for record in records]
        self.assertIn("goal_model_proposal", names)
        self.assertIn("goal_decision", names)
        self.assertNotIn("model_plan_review", names)
        final = next(r for r in records if r["kind"] == "goal_decision")
        self.assertEqual(final["details"]["model_calls"], 1)
        self.assertEqual(final["details"]["actions"][0],
                         goal("use", "breaker_box"))


class BackendFormat(unittest.TestCase):
    def test_llamacpp_uses_new_schema_in_one_request(self):
        captured = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n):
                return json.dumps({"choices": [{"message": {
                    "content": json.dumps(raw_plan([goal("use", "breaker_box")]))
                }}]}).encode()
        def fetch(req, timeout):
            captured.append(json.loads(req.data))
            return Response()
        with patch("ai_bridge.agent.request.urlopen", side_effect=fetch):
            result = LlamaCppBackend().plan_goals([{"role": "user", "content": "Power on"}])
        self.assertEqual(result["goals"], [goal("use", "breaker_box")])
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["response_format"]["schema"], GOAL_SCHEMA)

    def test_ollama_uses_new_schema_in_one_request(self):
        captured = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n):
                return json.dumps({"message": {
                    "content": json.dumps(raw_plan([goal("use", "breaker_box")]))
                }}).encode()
        def fetch(req, timeout):
            captured.append(json.loads(req.data))
            return Response()
        with patch("ai_bridge.agent.request.urlopen", side_effect=fetch):
            result = OllamaBackend().plan_goals([{"role": "user", "content": "Power on"}])
        self.assertEqual(result["goals"], [goal("use", "breaker_box")])
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["format"], GOAL_SCHEMA)


if __name__ == "__main__":
    unittest.main()
