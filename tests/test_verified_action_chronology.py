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


class ReplayBackend(ReactionBackend):
    """Production-shaped single-pass planner + model reaction, no real GGUF."""
    def __init__(self, plan, reaction):
        super().__init__()
        self.plan, self.reaction = plan, reaction
        self.planner_inputs = []

    def plan_goals(self, messages):
        self.planner_inputs.append(messages)
        return {"kind": "action", "speech": "I'll try that.",
                "emotion": "curious", "goals": self.plan}

    def converse(self, messages):
        self.inputs.append(messages)
        return self.reaction


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

    def _production_replay(self, session, text, plan, initial, reaction):
        model = ReplayBackend(plan, reaction)
        agent = Agent(model, self.store, PERSONA)
        decision = agent.decide(session, text, initial)
        self.assertEqual(len(model.planner_inputs), 1)
        self.assertEqual(len(decision.actions), len(plan))
        return agent, model

    def _receipt(self, model):
        self.assertEqual(len(model.inputs), 1, "One reaction for the whole sequence")
        prompt = model.inputs[0][-1]["content"]
        marker = "VERIFIED THIS-TURN PHYSICAL RECEIPT (system truth): "
        self.assertIn(marker, prompt)
        # Decode the JSON receipt alone, not later natural-language directions.
        return json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1])[0]

    def test_uploaded_light_stick_request_preserves_both_felt_actions(self):
        initial = world()
        agent, backend = self._production_replay(
            "flashlight_turn",
            "Go use your fingers to grasp the light stick on the surface over "
            "there, and make it so light comes out of it",
            [{"action": "take", "target": "flashlight", "argument": ""},
             {"action": "use", "target": "flashlight", "argument": "on"}],
            initial,
            "I got the flashlight on. That's much better, though this place still worries me.")
        taken = {**initial, "actor_at": "flashlight", "inventory": ["flashlight"]}
        switched = {**taken, "flashlight_on": True}
        agent.outcome("flashlight_turn", "take", "flashlight", True,
                      "Eli picked up the flashlight from the desk. It is now in inventory.",
                      taken, speak=False)
        self.assertFalse(backend.inputs)
        reply = agent.outcome("flashlight_turn", "use", "flashlight", True,
                              "Eli switched on the handheld flashlight.",
                              switched)
        self.assertIn("flashlight on", reply.speech)
        receipt = self._receipt(backend)
        events = receipt["verified_steps_this_turn"]
        self.assertEqual([e["action"] for e in events], ["take", "use"])
        self.assertFalse(receipt["turn_started_with"]["flashlight_on"])
        self.assertTrue(events[-1]["world_after"]["flashlight_on"])
        self.assertEqual(events[0]["world_after"]["inventory"], ["flashlight"])
        self.assertEqual(receipt["prior_attempts_of_this_exact_operation"], 0)
        self.assertEqual(self.store.load("flashlight_turn")["pending_turn_events"], [])

    def test_uploaded_breaker_then_survey_reacts_to_restoring_power(self):
        initial = world()
        initial["inventory"] = ["flashlight"]
        initial["flashlight_on"] = True
        agent, backend = self._production_replay(
            "power_turn",
            "I think you should go try turning on the breaker to see if that "
            "helps with the light",
            [{"action": "use", "target": "breaker_box", "argument": "on"},
             {"action": "survey", "target": "room", "argument": ""}],
            initial,
            "I flipped the breaker and the overhead lights came on. "
            "Those knocks from behind the door have me nervous.")
        powered = {**initial, "lights_on": True, "heard_knocks": True,
                   "actor_at": "breaker_box"}
        after = {**powered, "last_observation": "Eli looked around the bright room."}
        agent.outcome("power_turn", "use", "breaker_box", True,
                      "Eli flipped the breaker up. Power was restored, the "
                      "overhead lights switched on, and a folded note appeared. "
                      "Three knocks sounded behind the exit door.",
                      powered, speak=False)
        reply = agent.outcome("power_turn", "survey", "room", True,
                              "Eli looked around. Both lights are on and the "
                              "keypad glows red beside the locked door.", after)
        self.assertIn("flipped the breaker", reply.speech)
        receipt = self._receipt(backend)
        self.assertEqual([event["target"] for event in receipt["verified_steps_this_turn"]],
                         ["breaker_box", "room"])
        self.assertFalse(receipt["turn_started_with"]["lights_on"])
        self.assertTrue(receipt["verified_steps_this_turn"][0]["world_after"]["lights_on"])
        self.assertEqual(receipt["prior_attempts_of_this_exact_operation"], 0)
        self.assertEqual(self.store.load("power_turn")["facts"][-1]["action"], "survey")

    def test_new_operator_turn_drops_unspoken_events_from_aborted_queue(self):
        room = world()
        agent, backend = self._production_replay(
            "aborted", "Pick up the flashlight.",
            [{"action": "take", "target": "flashlight", "argument": ""}],
            room, "I inspected the breaker. Nothing obvious.")
        holding = {**room, "inventory": ["flashlight"]}
        agent.outcome("aborted", "take", "flashlight", True,
                      "Eli picked up the flashlight.", holding, speak=False)
        self.assertEqual(len(self.store.load("aborted")["pending_turn_events"]), 1)
        backend.plan = [{"action": "inspect", "target": "breaker_box", "argument": ""}]
        agent.decide("aborted", "Inspect the breaker.",
                     {**holding, "lights_on": False})
        agent.outcome("aborted", "inspect", "breaker_box", True,
                      "Eli inspected the breaker.", holding)
        receipt = self._receipt(backend)
        self.assertEqual([(e["action"], e["target"])
                          for e in receipt["verified_steps_this_turn"]],
                         [("inspect", "breaker_box")])
        self.assertEqual(receipt["prior_attempts_of_this_exact_operation"], 0)

    def test_failed_final_step_still_remembers_succeeded_prerequisite(self):
        room = world()
        agent, backend = self._production_replay(
            "failed", "Grab the flashlight and switch it on.",
            [{"action": "take", "target": "flashlight", "argument": ""},
             {"action": "use", "target": "flashlight", "argument": "on"}],
            room, "I tried the switch, but nothing happened. Something is wrong.")
        holding = {**room, "inventory": ["flashlight"]}
        agent.outcome("failed", "take", "flashlight", True,
                      "Eli picked up the flashlight.", holding, speak=False)
        agent.outcome("failed", "use", "flashlight", False,
                      "The flashlight did not switch on.", holding)
        receipt = self._receipt(backend)
        self.assertEqual([e["success"] for e in receipt["verified_steps_this_turn"]],
                         [True, False])
        self.assertEqual(len(self.store.load("failed")["facts"]), 2)

    def test_receipt_accepts_truthful_intermediate_action_not_other_invention(self):
        room = world()
        room["lights_on"] = True
        receipt = [
            {"action": "use", "target": "breaker_box", "success": True,
             "description": "Eli flipped the breaker and the lights came on."},
            {"action": "survey", "target": "room", "success": True,
             "description": "Eli looked around the room."},
        ]
        self.assertIn("flipped the breaker", Agent._ground_verified_outcome(
            "I flipped the breaker. It got brighter.", "survey", "room",
            True, receipt[-1]["description"], room, turn_events=receipt))
        self.assertEqual(Agent._ground_verified_outcome(
            "I opened the door and stepped outside.", "survey", "room",
            True, receipt[-1]["description"], room, turn_events=receipt), "")

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
