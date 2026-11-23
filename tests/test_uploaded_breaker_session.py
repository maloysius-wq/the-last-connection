"""User-uploaded session ZIP regression: Eli MUST approach and use breaker.

The actual 2026-11-23 GGUF proposals were semantically correct but used
"on"/"flip_up" for an argument-free breaker engine action and paraphrased
"flip the lever so it's up" as "flip the lever up". They were rejected by
the bridge before reaching Godot. This fixture reproduces those failures.

Do not turn quoted hypotheticals, negations, reversed lever directions or
guessed keypad codes into authorized physical actions.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.semantic import PlanRejected, validated_steps
from test_semantic_planner import proposed, step, world
from test_action_completeness_review import AuditedBackend, audited

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"

FIRST = ("Okay.  Go ahead and go to the breaker box and try turning it on.  "
         "We'll see if that restores power in the room.")
FIRST_DRAFT = [step("move_to", "breaker_box", "go to the breaker box")]
FIRST_REVIEW = [
    step("move_to", "breaker_box", "go to the breaker box"),
    step("use", "breaker_box", "try turning it on", "on"),
]
SECOND = ("I mean from what I can tell, it's for the room lights.  "
          "I think it will turn on the lights.  "
          "Please go over and flip the lever so it's up.")
SECOND_DRAFT = [
    step("move_to", "breaker_box", "go over and flip the lever up"),
    step("use", "breaker_box", "flip the lever up", "flip_up"),
]

EXPECTED = (
    {"action": "move_to", "target": "breaker_box", "argument": ""},
    {"action": "use", "target": "breaker_box", "argument": ""},
)


def actual_world():
    w = world()
    w["actor_at"] = "flashlight"
    w["inventory"] = ["flashlight"]
    w["flashlight_on"] = True
    w["lights_on"] = False
    return w


class SessionBreakerFailures(unittest.TestCase):
    def decide(self, message, draft, review):
        with TemporaryDirectory() as temp:
            backend = AuditedBackend(proposed("action", draft,
                    speech="Okay, I'll go over and try that switch."),
                                     audited(review))
            agent = Agent(backend, SessionStore(Path(temp)), PERSONA)
            result = agent.decide("user_uploaded_session", message, actual_world())
            self.assertNotEqual(result.action, "wait")
            self.assertEqual(result.actions, EXPECTED)
            self.assertEqual((result.action, result.target), ("move_to", "breaker_box"))
            self.assertEqual(backend.interpret_calls, 1)
            self.assertEqual(backend.review_calls, 1)
            return result

    def test_first_actual_turn_reviewer_recovers_missing_use(self):
        self.decide(FIRST, FIRST_DRAFT, FIRST_REVIEW)

    def test_second_actual_turn_accepts_near_quote_and_flip_up(self):
        self.decide(SECOND, SECOND_DRAFT, SECOND_DRAFT)

    def test_direct_validation_normalizes_but_preserves_requested_goal(self):
        self.assertEqual(validated_steps(FIRST_REVIEW, FIRST, actual_world()),
                         EXPECTED)
        self.assertEqual(validated_steps(SECOND_DRAFT, SECOND, actual_world()),
                         EXPECTED)

    def test_breaker_use_without_argument_is_unchanged(self):
        text = "Turn on the breaker."
        self.assertEqual(validated_steps([
            step("use", "breaker_box", "Turn on the breaker", "")
        ], text, actual_world())[0]["argument"], "")

    def test_door_open_argument_is_action_not_a_code(self):
        text = "Go open the door."
        plan = validated_steps([
            step("use", "exit_door", "open the door", "open")
        ], text, actual_world())
        self.assertEqual(plan[0]["argument"], "")

    def test_no_opposite_breaker_direction(self):
        text = "Flip the breaker down."
        for arg in ("on", "flip_up", "off", ""):
            with self.subTest(arg=arg), self.assertRaises(PlanRejected):
                validated_steps([step("use", "breaker_box", "Flip the breaker down", arg)],
                                text, actual_world())

    def test_different_polarity_fuzzy_quote_rejected(self):
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("use", "breaker_box", "flip the lever up", "flip_up")
            ], "Please flip the lever down.", actual_world())

    def test_no_invented_commands_or_new_goals_from_fuzzy_evidence(self):
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("use", "breaker_box", "flip the lever up", "flip_up")
            ], "Please inspect the keypad.", actual_world())

    def test_negated_instruction_not_accepted_even_with_fuzzy_quote(self):
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("use", "breaker_box", "flip the lever up", "flip_up")
            ], "Don't flip the lever so it's up.", actual_world())

    def test_hypothetical_does_not_grant_world_action(self):
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("use", "breaker_box", "flip the lever up", "flip_up")
            ], "What if you flip the lever so it's up?", actual_world())

    def test_power_and_keypad_code_safeguards_still_hold(self):
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("enter_code", "keypad", "enter the code", "4317")
            ], "Please enter the code.", actual_world())


if __name__ == "__main__":
    unittest.main()
