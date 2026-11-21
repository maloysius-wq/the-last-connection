"""Regress a valid three-step instruction wrongly rejected by the GGUF review.

The operator should not have to guess which AI JSON quote or second-model
interpretation caused Eli to say "I'm not completely sure which actions..."
No tests grant the AI world authority: every plan must pass current-user
evidence and engine-state constraints.
"""
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.semantic import validated_steps, PlanRejected
from test_semantic_planner import proposed, step, world
from test_action_completeness_review import audited, AuditedBackend

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"
SCREENSHOT = (
    "I won't make you do anything reckless, I promise. "
    "Let's work through this together. "
    "Go pick up that flashlight, turn it on, and then look around the room. "
    "Tell me if you see anything new."
)

PICKUP = step("take", "flashlight", "pick up that flashlight")
ON = step("use", "flashlight", "turn it on", "on")
SURVEY = step("survey", "room", "look around the room")
FULL_PLAN = [PICKUP, ON, SURVEY]


class TestScreenshotPlanRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def decide(self, player, initial, reviewer):
        backend = AuditedBackend(initial, reviewer)
        agent = Agent(backend, self.store, PERSONA)
        result = agent.decide("real_screenshot", player, world())
        return result, backend

    def assert_complete(self, decision):
        self.assertEqual(
            [(a["action"], a["target"], a["argument"])
             for a in decision.actions],
            [("take", "flashlight", ""),
             ("use", "flashlight", "on"),
             ("survey", "room", "")])
        self.assertEqual((decision.action, decision.target), ("take", "flashlight"))
        self.assertNotIn("clarify", decision.speech.lower())
        self.assertIn("look around", decision.speech.lower())

    def test_exact_screenshot_full_two_pass_plan(self):
        result, backend = self.decide(
            SCREENSHOT, proposed("action", FULL_PLAN), audited(FULL_PLAN))
        self.assert_complete(result)
        self.assertEqual(backend.interpret_calls, 1)
        self.assertEqual(backend.review_calls, 1)

    def test_reviewer_clarification_does_not_veto_full_valid_plan(self):
        result, _ = self.decide(
            SCREENSHOT, proposed("action", FULL_PLAN),
            audited([], "clarify", "could not decide"))
        self.assert_complete(result)

    def test_reviewer_unverifiable_quote_does_not_veto_full_plan(self):
        bad = [
            PICKUP, ON,
            step("survey", "room", "look at the ceiling that wasn't mentioned")
        ]
        result, _ = self.decide(
            SCREENSHOT, proposed("action", FULL_PLAN), audited(bad))
        self.assert_complete(result)

    def test_first_pass_dropped_on_and_survey_but_review_recovers_both(self):
        result, _ = self.decide(
            SCREENSHOT, proposed("action", [PICKUP]), audited(FULL_PLAN))
        self.assert_complete(result)

    def test_first_pass_mistook_explicit_commands_for_clarification(self):
        result, backend = self.decide(
            SCREENSHOT, proposed("clarify", speech="Which actions do you mean?"),
            audited(FULL_PLAN))
        self.assert_complete(result)
        self.assertEqual(backend.review_calls, 1)

    def test_first_pass_mistook_commands_for_conversation(self):
        result, backend = self.decide(
            SCREENSHOT, proposed("conversation", speech="I'll listen."),
            audited(FULL_PLAN))
        self.assert_complete(result)
        self.assertEqual(backend.review_calls, 1)

    def test_first_pass_full_second_pass_omitted_switch_on(self):
        result, _ = self.decide(
            SCREENSHOT, proposed("action", FULL_PLAN),
            audited([PICKUP, SURVEY]))
        self.assert_complete(result)

    def test_review_includes_redundant_explicit_walk_to_flashlight(self):
        reviewed = [
            step("move_to", "flashlight", "Go pick up that flashlight"),
            PICKUP, ON, SURVEY,
        ]
        # A broad evidence span at step 1 overlaps step 2; each starts at
        # distinct source words, and the engine does its own approach.
        result, _ = self.decide(
            SCREENSHOT, proposed("action", FULL_PLAN), audited(reviewed))
        self.assert_complete(result)

    def test_first_pass_only_walked_but_reviewer_completed_request(self):
        first = [step("move_to", "flashlight", "Go pick up that flashlight")]
        result, _ = self.decide(
            SCREENSHOT, proposed("action", first), audited(FULL_PLAN))
        self.assert_complete(result)

    def test_review_adds_unrelated_extra_action_but_original_is_complete(self):
        player = (
            "I see the exit door. Go pick up that flashlight, turn it on, "
            "and then look around the room."
        )
        original = [
            step("take", "flashlight", "pick up that flashlight"),
            step("use", "flashlight", "turn it on", "on"),
            step("survey", "room", "look around the room")
        ]
        reviewed = [
            step("move_to", "exit_door", "I see the exit door"),
            *original
        ]
        result, _ = self.decide(player, proposed("action", original), audited(reviewed))
        self.assert_complete(result)

    def test_review_combines_pickup_and_switch_as_one_engine_action(self):
        reviewed = [
            step("use", "flashlight", "turn it on", "on"),
            SURVEY,
        ]
        result, _ = self.decide(
            SCREENSHOT, proposed("action", FULL_PLAN), audited(reviewed))
        self.assert_complete(result)

    def test_redundant_survey_for_report_is_collapsed(self):
        with_report = FULL_PLAN + [
            step("survey", "room", "Tell me if you see anything new")
        ]
        self.assertEqual(
            validated_steps(with_report, SCREENSHOT, world()),
            tuple({"action": s["action"], "target": s["target"], "argument": s["argument"]}
                  for s in FULL_PLAN))
        result, _ = self.decide(
            SCREENSHOT, proposed("action", with_report), audited(FULL_PLAN))
        self.assert_complete(result)

    def test_model_uses_inspect_room_as_survey(self):
        plan = [PICKUP, ON, step("inspect", "room", "look around the room")]
        self.assertEqual(validated_steps(plan, SCREENSHOT, world())[-1],
                         {"action": "survey", "target": "room", "argument": ""})

    def test_first_evidence_quote_can_cover_multiple_actions(self):
        long_quote = step(
            "take", "flashlight",
            "Go pick up that flashlight, turn it on, and then look around the room")
        result, _ = self.decide(
            SCREENSHOT, proposed("action", [long_quote, ON, SURVEY]),
            audited(FULL_PLAN))
        self.assert_complete(result)

    def test_one_unresolved_step_cannot_be_silently_removed(self):
        text = "Pick up the flashlight, then punch 9999 into the keypad."
        # The independent reviewer invents a code by quoting an unrelated
        # span; neither plan may execute a first action on that basis.
        initial = proposed("action", [step("take", "flashlight", "Pick up the flashlight")])
        reviewer = audited([
            step("take", "flashlight", "Pick up the flashlight"),
            step("enter_code", "keypad", "into the keypad", "9999")
        ])
        decision, _ = self.decide(text, initial, reviewer)
        self.assertEqual(decision.actions, ())
        self.assertEqual(decision.action, "wait")

    def test_observing_a_door_is_not_a_command_to_walk_to_it(self):
        text = "I see the exit door. Go pick up that flashlight."
        with self.assertRaises(PlanRejected):
            validated_steps([
                step("move_to", "exit_door", "I see the exit door"),
                step("take", "flashlight", "pick up that flashlight"),
            ], text, world())

    def test_no_hypothetical_side_effects(self):
        text = "What if you picked up the flashlight and opened the door?"
        plan = [
            step("take", "flashlight", "picked up the flashlight"),
            step("use", "exit_door", "opened the door"),
        ]
        with self.assertRaises(PlanRejected):
            validated_steps(plan, text, world())


if __name__ == "__main__":
    unittest.main()
