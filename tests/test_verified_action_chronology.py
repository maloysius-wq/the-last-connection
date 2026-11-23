"""Physical-memory provenance for the single-pass local Eli agent.

A visible property is NOT evidence Eli already inspected it. Only actual
Godot outcomes authorize counting earlier checks or claiming a transition.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from test_semantic_planner import world

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


class ReactionBackend:
    def __init__(self):
        self.inputs = []
    def converse(self, messages):
        self.inputs.append(messages)
        return "I checked the breaker. The lever is down."
    def plan_goals(self, messages):
        raise AssertionError("An outcome is not a new action request")


class ChronologyRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = SessionStore(Path(self.tmp.name))
        self.backend = ReactionBackend()
        self.agent = Agent(self.backend, self.store, PERSONA)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_inspection_is_not_a_recheck(self):
        current = world()
        current["actor_at"] = "breaker_box"
        current["last_observation"] = (
            "Eli inspected the breaker. Its lever is down and the lights are out.")
        result = self.agent.outcome(
            "memory_first", "inspect", "breaker_box", True,
            current["last_observation"], current)
        self.assertIn("breaker", result.speech)
        self.assertEqual(len(self.backend.inputs), 1)
        request = self.backend.inputs[0][-1]["content"]
        self.assertIn('"prior_attempts_of_this_exact_operation":0', request)
        self.assertIn('"prior_confirmed_operations_on_this_object":[]', request)
        self.assertIn('"is_this_first_attempt_of_this_operation":true', request)
        system = self.backend.inputs[0][0]["content"]
        self.assertIn('"action":"inspect","target":"breaker_box","attempts":1', system)

    def test_second_check_has_real_provenance_not_just_an_observation(self):
        room = world()
        room["actor_at"] = "breaker_box"
        self.agent.outcome(
            "memory_repeat", "inspect", "breaker_box", True,
            "Eli inspected the breaker. Lever down.", room)
        self.agent.outcome(
            "memory_repeat", "inspect", "breaker_box", True,
            "Eli inspected the breaker again. Lever down.", room)
        request = self.backend.inputs[-1][-1]["content"]
        self.assertIn('"prior_attempts_of_this_exact_operation":1', request)
        self.assertIn('"is_this_first_attempt_of_this_operation":false', request)
        self.assertEqual(
            self.agent._confirmed_event_ledger(
                self.store.load("memory_repeat")["facts"])["operation_counts"],
            [{"action": "inspect", "target": "breaker_box",
              "attempts": 2, "successes": 2}])

    def test_earlier_look_does_not_count_as_earlier_operation(self):
        room = world()
        self.store.save("memory_speech", {
            "facts": [],
            "history": [{"role": "assistant",
                         "content": "I checked the breaker twice earlier."}],
        })
        self.agent.outcome(
            "memory_speech", "inspect", "breaker_box", True,
            "Eli checked the breaker. The lever is down.", room)
        event_prompt = self.backend.inputs[-1][-1]["content"]
        self.assertIn('"prior_attempts_of_this_exact_operation":0', event_prompt)
        ledger = self.agent._confirmed_event_ledger(
            self.store.load("memory_speech")["facts"])
        self.assertEqual(ledger["operation_counts"][0]["attempts"], 1)

    def test_other_target_action_does_not_make_first_inspection_a_repeat(self):
        room = world()
        self.agent.outcome(
            "memory_other", "use", "flashlight", True,
            "Eli switched on the flashlight.",
            {**room, "inventory": ["flashlight"], "flashlight_on": True},
            speak=False)
        self.agent.outcome(
            "memory_other", "inspect", "breaker_box", True,
            "Eli looked at the breaker. The lever is down.", room)
        prompt = self.backend.inputs[-1][-1]["content"]
        self.assertIn('"prior_attempts_of_this_exact_operation":0', prompt)
        self.assertIn('"prior_confirmed_operations_on_this_object":[]', prompt)

    def test_after_escape_model_knows_it_is_not_still_in_room(self):
        room = world(note=True)
        room["escaped"] = True
        room["door_unlocked"] = True
        room["actor_at"] = "exit_door"
        self.agent.outcome(
            "memory_escape", "use", "exit_door", True,
            "Eli opened the unlocked door and stepped out of camera view.",
            room)
        system = self.backend.inputs[-1][0]["content"]
        self.assertIn("outside the camera view", system)
        self.assertIn('"escaped":true', system)

    def test_engine_history_saved_before_speech(self):
        room = world()
        self.agent.outcome(
            "memory_persist", "inspect", "breaker_box", True,
            "Eli inspected the breaker.", room, speak=False)
        self.assertEqual(len(self.backend.inputs), 0)
        result = self.store.load("memory_persist")
        self.assertEqual(len(result["facts"]), 1)
        self.assertEqual(result["facts"][0]["target"], "breaker_box")


if __name__ == "__main__":
    unittest.main()
