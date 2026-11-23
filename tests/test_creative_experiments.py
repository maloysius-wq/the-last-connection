"""Creative experiments are executable attempts, not imagined puzzle progress."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.semantic import PlanRejected, validated_steps
from test_semantic_planner import proposed, step, world

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


def expanded_room():
    room = world()
    for name in ("desk", "wall", "floor", "ceiling"):
        room["objects"][name] = {"visible": True, "description":
                                 "An ordinary part of the room."}
    return room


class CreativeBackend:
    def __init__(self, proposal):
        self.proposal = proposal
    def interpret(self, messages):
        return self.proposal
    def converse(self, messages):
        return "All right, I'll try it. No idea if this is going to help."


class ExperimentPlanningTests(unittest.TestCase):
    def test_weird_actions_are_valid_authorized_primitive(self):
        text = "Try to knock on the door three times."
        plan = validated_steps([
            step("experiment", "exit_door", "knock on the door", "knock three times")
        ], text, expanded_room())
        self.assertEqual(plan[0]["action"], "experiment")
        self.assertEqual(plan[0]["target"], "exit_door")
        self.assertEqual(plan[0]["argument"], "knock three times")

    def test_in_place_weird_action_has_no_predefined_target(self):
        text = "Do a little dance."
        plan = validated_steps([
            step("experiment", "room", "Do a little dance", "dance in place")
        ], text, expanded_room())
        self.assertEqual(plan[0]["argument"], "dance in place")

    def test_hypothetical_is_not_an_action(self):
        text = "What if you kicked the door?"
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("experiment", "exit_door", "kicked the door", "kick it")
            ], text, expanded_room())

    def test_negated_creative_request_does_not_execute(self):
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("experiment", "exit_door", "Don't kick the door", "kick the door")
            ], "Don't kick the door.", expanded_room())

    def test_hidden_note_is_not_available_for_experiment(self):
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("experiment", "maintenance_note", "shake the note", "shake it")
            ], "Shake the note.", expanded_room())

    def test_no_infinite_or_multiline_freeform_payload(self):
        for bad in ("", "x"*121, "knock\nopen door"):
            with self.subTest(bad=bad):
                with self.assertRaises(PlanRejected):
                    validated_steps([
                        step("experiment", "room", "Do a little dance", bad)
                    ], "Do a little dance.", expanded_room())

    def test_direct_model_experiment_routes_to_engine(self):
        proposal = proposed("action", [
            step("experiment", "room", "Do a little dance", "dance in place")
        ], speech="Okay, I'll try it. I'm terrified, but fine.")
        with TemporaryDirectory() as tmp:
            agent = Agent(CreativeBackend(proposal), SessionStore(Path(tmp)), PERSONA)
            result = agent.decide("weird", "Do a little dance.", expanded_room())
            self.assertEqual(result.action, "experiment")
            self.assertEqual(result.actions[0]["argument"], "dance in place")
            self.assertIn("I'll try", result.speech)

    def test_code_entry_still_needs_explicit_user_digit_authorization(self):
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("enter_code", "keypad", "try the keypad", "4317")
            ], "Try the keypad.", expanded_room())


if __name__ == "__main__":
    unittest.main()
