"""Real screenshot regression: semantic planner omitted requested flashlight ON.

A valid one-step pickup is NOT enough for a multi-step instruction. Production
backends independently audit every physical plan before passing it to Godot.
The old scripted test backends continue without needing a second model.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from ai_bridge.agent import Agent, BackendUnavailable, LlamaCppBackend, OllamaBackend, SessionStore
from ai_bridge.semantic import REVIEW_SCHEMA, needs_action_review, is_reflective_question
from test_semantic_planner import world, proposed, step

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"
SCREENSHOT = (
    "Let's just start with picking up the flashlight on the table there, "
    "and turning it on."
)


class AuditedBackend:
    def __init__(self, draft, reviewed):
        self.draft, self.reviewed = draft, reviewed
        self.interpret_calls = 0
        self.review_calls = 0
        self.conversation_calls = 0
        self.last_review_input = None

    def interpret(self, messages):
        self.interpret_calls += 1
        return self.draft

    def review(self, messages):
        self.review_calls += 1
        self.last_review_input = messages
        if isinstance(self.reviewed, Exception):
            raise self.reviewed
        return self.reviewed

    def converse(self, messages):
        self.conversation_calls += 1
        return self.draft.get("speech", "I don't know yet.")

    def respond(self, messages):
        raise AssertionError("No old regex single-action fallback")


def audited(steps, kind="action", reason="Full independent review"):
    return {"kind": kind, "steps": list(steps), "reason": reason}


class TestActionCompleteness(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def decide(self, message, draft, reviewer):
        backend = AuditedBackend(draft, reviewer)
        agent = Agent(backend, self.store, PERSONA)
        decision = agent.decide("review", message, world())
        self.assertEqual(backend.interpret_calls,
                         0 if is_reflective_question(message) else 1)
        if is_reflective_question(message):
            self.assertGreaterEqual(backend.conversation_calls, 1)
        if (not is_reflective_question(message) and draft["kind"] == "action"
                and needs_action_review(message, draft["steps"])):
            self.assertEqual(backend.review_calls, 1)
            self.assertIn("ACTION COMPLETENESS AUDITOR",
                          backend.last_review_input[0]["content"])
            review_request = json.loads(backend.last_review_input[1]["content"])
            self.assertEqual(review_request["current_player_message"], message)
            self.assertEqual(review_request["draft_steps_not_yet_executed"],
                             draft["steps"])
        else:
            self.assertEqual(backend.review_calls, 0)
        return decision

    def test_exact_screenshot_first_draft_pickup_only_repaired_by_auditor(self):
        first = proposed("action", [
            step("take", "flashlight",
                 "picking up the flashlight on the table there")])
        reviewer = audited([
            step("take", "flashlight",
                 "picking up the flashlight on the table there"),
            step("use", "flashlight", "turning it on", "on"),
        ])
        result = self.decide(SCREENSHOT, first, reviewer)
        self.assertEqual(list(result.actions), [
            {"action": "take", "target": "flashlight", "argument": ""},
            {"action": "use", "target": "flashlight", "argument": "on"},
        ])
        self.assertEqual(result.action, "take")
        self.assertEqual(result.actions[-1]["argument"], "on")
        self.assertNotIn("have picked", result.speech)

    def test_auditor_compact_use_on_replaces_incomplete_pickup(self):
        result = self.decide(
            SCREENSHOT,
            proposed("action", [
                step("take", "flashlight", "picking up the flashlight on the table there")]),
            audited([step("use", "flashlight", "turning it on", "on")]))
        self.assertEqual(result.action, "use")
        self.assertEqual(result.argument, "on")
        self.assertEqual(result.actions[0]["action"], "use")

    def test_auditor_cannot_drop_valid_second_step(self):
        result = self.decide(
            SCREENSHOT,
            proposed("action", [
                step("take", "flashlight", "picking up the flashlight on the table there"),
                step("use", "flashlight", "turning it on", "on"),
            ]),
            audited([step("take", "flashlight",
                          "picking up the flashlight on the table there")]))
        self.assertEqual(len(result.actions), 2)
        self.assertEqual(result.actions[-1]["argument"], "on")

    def test_unrelated_review_plan_cancels_whole_sequence(self):
        text = "Grab the flashlight, then go to the keypad."
        result = self.decide(
            text,
            proposed("action", [step("take", "flashlight", "Grab the flashlight")]),
            audited([step("move_to", "keypad", "go to the keypad")]))
        self.assertEqual(result.action, "wait")
        self.assertEqual(result.actions, ())
        self.assertEqual(result.actions, ())

    def test_hypothetical_followup_cannot_make_simple_instruction_incomplete(self):
        text = "Pick up the flashlight. What if you opened the door?"
        result = self.decide(
            text,
            proposed("action", [step("take", "flashlight", "Pick up the flashlight")]),
            audited([
                step("take", "flashlight", "Pick up the flashlight"),
                step("use", "exit_door", "opened the door"),
            ]))
        # The one physical instruction is safe. A second model isn't allowed
        # to turn an unrelated speculative question into a command.
        self.assertEqual(result.action, "take")
        self.assertEqual(len(result.actions), 1)

    def test_simple_keypad_walk_needs_no_second_model_guess(self):
        text = "Go to the keypad, please."
        result = self.decide(
            text,
            proposed("action", [step("move_to", "keypad", "Go to the keypad")]),
            audited([
                step("move_to", "keypad", "Go to the keypad"),
                step("enter_code", "keypad", "please", "4317"),
            ]))
        self.assertEqual(result.action, "move_to")
        self.assertEqual(result.actions, (
            {"action": "move_to", "target": "keypad", "argument": ""},))

    def test_review_failure_cancels_without_attempting_first_action(self):
        result = self.decide(
            SCREENSHOT,
            proposed("action", [
                step("take", "flashlight", "picking up the flashlight on the table there")]),
            BackendUnavailable("local llama.cpp review failed"))
        self.assertEqual(result.action, "wait")
        self.assertEqual(result.actions, ())

    def test_reviewer_asks_clarification_before_either_action(self):
        result = self.decide(
            SCREENSHOT,
            proposed("action", [
                step("take", "flashlight", "picking up the flashlight on the table there")]),
            audited([], kind="clarify", reason="Not sure what to do"))
        self.assertEqual(result.action, "wait")
        self.assertEqual(result.actions, ())

    def test_conversation_remains_one_inference_and_no_physical_actions(self):
        result = self.decide(
            "Do you think there's anything dangerous behind the door?",
            proposed("conversation", speech="I don't know. I don't like that door."),
            audited([]))
        self.assertEqual(result.action, "wait")
        self.assertEqual(result.actions, ())
        self.assertIn("don't like", result.speech)

    def test_auditor_repairs_three_step_prior_playtest(self):
        text = ("I see the flashlight. Go grab it, switch it on, "
                "and take a look around the room. Tell me what you see.")
        result = self.decide(
            text,
            proposed("action", [step("take", "flashlight", "grab it")]),
            audited([
                step("take", "flashlight", "grab it"),
                step("use", "flashlight", "switch it on", "on"),
                step("survey", "room", "take a look around the room"),
            ]))
        self.assertEqual([(s["action"], s["target"]) for s in result.actions],
                         [("take", "flashlight"), ("use", "flashlight"),
                          ("survey", "room")])


class ReviewBackendProtocolTests(unittest.TestCase):
    def test_llamacpp_structured_action_review_uses_same_model(self):
        recorded = []
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n):
                return json.dumps({"choices": [{"message": {"content":
                    json.dumps(audited([step("use", "flashlight",
                                             "turn it on", "on")]))}}]}).encode()
        def fetch(req, timeout):
            recorded.append((json.loads(req.data), timeout))
            return FakeResponse()
        with patch("ai_bridge.agent.request.urlopen", side_effect=fetch):
            result = LlamaCppBackend().review([{"role": "user", "content": "check"}])
        self.assertEqual(result["kind"], "action")
        sent, timeout = recorded[0]
        self.assertEqual(sent["model"], "tlc-eli")
        self.assertEqual(sent["response_format"]["schema"], REVIEW_SCHEMA)
        self.assertEqual(sent["stream"], False)
        self.assertEqual(timeout, 300)

    def test_ollama_structured_review_stays_local(self):
        recorded = []
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n):
                return json.dumps({"message": {"content": json.dumps(
                    audited([step("take", "flashlight", "pick it up")]))}}).encode()
        def fetch(req, timeout):
            recorded.append((json.loads(req.data), timeout))
            return FakeResponse()
        with patch("ai_bridge.agent.request.urlopen", side_effect=fetch):
            result = OllamaBackend().review([{"role": "user", "content": "check"}])
        self.assertEqual(result["kind"], "action")
        self.assertEqual(recorded[0][0]["format"], REVIEW_SCHEMA)
        self.assertIs(recorded[0][0]["think"], False)


if __name__ == "__main__":
    unittest.main()
