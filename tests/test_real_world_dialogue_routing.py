"""Regress real Windows conversation and flashlight-control screenshots.

Small GGUF duplicate reviews must not veto an unambiguous single directive;
asking "why did you resist?" must receive actual live dialogue, not a
structured-plan error. All other semantic actions remain engine-authorized.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.semantic import is_reflective_question, needs_action_review
from test_semantic_planner import world, step, proposed

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


class RecorderBackend:
    def __init__(self, response, spoken="I got confused. I'm sorry. I heard you, but I hesitated when I shouldn't have."):
        self.response = response
        self.spoken = spoken
        self.interprets = []
        self.conversations = []
        self.reviews = []

    def interpret(self, messages):
        self.interprets.append(messages)
        return self.response

    def converse(self, messages):
        self.conversations.append(messages)
        return self.spoken

    def review(self, messages):
        self.reviews.append(messages)
        # If this path runs for a simple directive, the bug is back.
        raise AssertionError("Simple directive should not trigger a second-model veto")


class TestRealWindowsDialogueFailures(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def decide(self, player, response, *, inventory=(), referent="", spoken=None):
        backend = RecorderBackend(response, spoken or
            "I got confused. I'm sorry. I heard you, but I hesitated when I shouldn't have.")
        w = world()
        w["inventory"] = list(inventory)
        w["flashlight_on"] = False
        agent = Agent(backend, self.store, PERSONA)
        self.store.save("screenshot", {"history": [], "facts": [], "referent": referent})
        result = agent.decide("screenshot", player, w)
        return result, backend

    def test_exact_screenshot_directive_resolves_held_flashlight(self):
        message = "Seriously? You are already holding it. Turn it on!"
        result, backend = self.decide(message, proposed("action", [
            step("use", "flashlight", "Turn it on", "on"),
        ]), inventory=("flashlight",))
        self.assertEqual((result.action, result.target, result.argument),
                         ("use", "flashlight", "on"))
        self.assertEqual(result.actions, (
            {"action": "use", "target": "flashlight", "argument": "on"},))
        self.assertEqual(len(backend.interprets), 1)
        self.assertEqual(len(backend.reviews), 0)
        self.assertEqual(len(backend.conversations), 0)
        self.assertIn("CURRENT SINGLE HELD ITEM: flashlight",
                      backend.interprets[0][0]["content"])

    def test_holding_reference_beats_stale_keypad_focus(self):
        result, _ = self.decide(
            "You are already holding it. Turn it on!",
            proposed("action", [step("use", "flashlight", "Turn it on", "on")]),
            inventory=("flashlight",), referent="keypad")
        self.assertEqual(result.action, "use")

    def test_no_held_or_referent_must_still_clarify(self):
        result, _ = self.decide("Turn it on!",
                                proposed("action", [
                                    step("use", "flashlight", "Turn it on", "on"),
                                ]))
        self.assertEqual(result.action, "wait")
        self.assertEqual(result.actions, ())

    def test_multiple_held_props_are_not_arbitrarily_selected(self):
        result, _ = self.decide("Turn it on!",
                                proposed("action", [
                                    step("use", "flashlight", "Turn it on", "on"),
                                ]), inventory=("flashlight", "keypad"))
        self.assertEqual(result.action, "wait")

    def test_explicit_named_flashlight_command_is_one_step(self):
        result, backend = self.decide(
            "TURN ON THE FUCKING FLASHLIGHT",
            proposed("action", [
                step("use", "flashlight", "TURN ON THE FUCKING FLASHLIGHT", "on"),
            ]))
        self.assertEqual((result.action, result.target, result.argument),
                         ("use", "flashlight", "on"))
        self.assertEqual(len(backend.reviews), 0)

    def test_exact_screenshot_why_question_gets_natural_reply(self):
        message = "Damn dude. That was like pulling teeth. Why did you resist so much?"
        # Even if the structured planner would have mislabeled this as an
        # action, conversation routes directly to unstructured local dialogue.
        result, backend = self.decide(
            message, proposed("action", [
                step("use", "exit_door", "resist so much"),
            ]), inventory=("flashlight",))
        self.assertEqual(result.action, "wait")
        self.assertEqual(result.actions, ())
        self.assertIn("I got confused", result.speech)
        self.assertEqual(len(backend.interprets), 0)
        self.assertEqual(len(backend.reviews), 0)
        self.assertEqual(len(backend.conversations), 1)
        self.assertEqual(backend.conversations[0][-1]["content"], message)

    def test_followup_question_does_not_issue_physical_actions(self):
        result, backend = self.decide(
            "Why did you wait? What were you thinking?",
            proposed("action", [step("take", "flashlight", "you wait")]))
        self.assertEqual(result.action, "wait")
        self.assertEqual(len(backend.conversations), 1)

    def test_question_followed_by_order_still_executes(self):
        result, backend = self.decide(
            "Why were you hesitant? Turn on the flashlight!",
            proposed("action", [
                step("use", "flashlight", "Turn on the flashlight", "on"),
            ]))
        self.assertEqual(result.action, "use")
        self.assertEqual(len(backend.interprets), 1)
        self.assertEqual(len(backend.conversations), 0)

    def test_hypothetical_why_is_conversation_and_suggestion_is_not(self):
        self.assertTrue(is_reflective_question("Why did you hesitate?"))
        self.assertTrue(is_reflective_question("What if you opened the door?"))
        self.assertFalse(is_reflective_question("Why don't you grab the flashlight?"))
        self.assertFalse(is_reflective_question("How about looking around?"))
        self.assertFalse(is_reflective_question("Seriously? Turn it on!"))

    def test_only_compound_requests_get_extra_review(self):
        self.assertFalse(needs_action_review(
            "Seriously? You are already holding it. Turn it on!",
            [step("use", "flashlight", "Turn it on", "on")]))
        self.assertFalse(needs_action_review(
            "TURN ON THE FUCKING FLASHLIGHT",
            [step("use", "flashlight", "TURN ON THE FUCKING FLASHLIGHT", "on")]))
        self.assertTrue(needs_action_review(
            "Pick up the flashlight and turn it on.",
            [step("take", "flashlight", "Pick up the flashlight")]))
        self.assertTrue(needs_action_review(
            "Go to the breaker. Read the note.",
            [step("move_to", "breaker_box", "Go to the breaker")]))


if __name__ == "__main__":
    unittest.main()
