"""Regression reproductions from the user's actual 2026-11-23 session ZIP.

Do not accept model-invented digits, older action evidence, or implied
physical state. Godot must be able to approach a target on a direct USE.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.semantic import PlanRejected, validated_steps, contains_explicit_action_request
from test_semantic_planner import proposed, step, world
from test_action_completeness_review import AuditedBackend, audited

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"
CODE_FACT = {
    "action": "inspect", "target": "maintenance_note", "success": True,
    "description": ("The maintenance note reads: 'RESET SEQUENCE 4317'. "
                    "Below it someone scrawled: 'Don't listen to the knocking.'")
}


def room():
    data = world(note=True)
    data["actor_at"] = "maintenance_note"
    data["lights_on"] = True
    data["inventory"] = ["flashlight"]
    data["flashlight_on"] = True
    data["objects"]["exit_door"]["description"] = "Heavy locked door."
    return data


class RealSessionRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))
        self.session = "real_session"

    def tearDown(self):
        self.temp.cleanup()

    def decide(self, user, first, review, *, prior_facts=None, referent=""):
        self.store.save(self.session, {"history": [], "facts": prior_facts or [],
                                       "referent": referent})
        backend = AuditedBackend(first, review)
        agent = Agent(backend, self.store, PERSONA)
        result = agent.decide(self.session, user, room())
        return result, backend

    def test_uploaded_go_to_pinpad_input_that_confirmed_code(self):
        text = ("Yeah that is pretty weird.  Well it looks like that's our "
                "code - go over to the pinpad and input that code and we'll "
                "see if that opens the door!")
        draft = proposed("action", [
            step("move_to", "keypad", "go over to the pinpad"),
            step("enter_code", "keypad", "input that code", "4317"),
        ])
        result, backend = self.decide(text, draft, audited(draft["steps"]),
                                      prior_facts=[CODE_FACT],
                                      referent="maintenance_note")
        self.assertEqual([(p["action"], p["target"]) for p in result.actions],
                         [("move_to", "keypad"), ("enter_code", "keypad")])
        self.assertEqual(result.actions[1]["argument"], "4317")
        self.assertEqual(backend.review_calls, 1)

    def test_uploaded_enter_the_code_with_stale_walk_quote(self):
        text = "Enter the code into the keypad"
        draft = proposed("action", [
            step("move_to", "keypad", "GO TO THE KEYPAD"),
            step("enter_code", "keypad", "enter the code into the keypad", "4317"),
        ])
        result, backend = self.decide(text, draft, audited(draft["steps"]),
                                      prior_facts=[CODE_FACT], referent="keypad")
        self.assertEqual(result.actions, (
            {"action": "enter_code", "target": "keypad", "argument": "4317"},))
        self.assertEqual(backend.review_calls, 1)

    def test_uploaded_press_it_now_uses_known_code_not_old_quote(self):
        text = "Press it NOW"
        draft = proposed("action", [
            step("move_to", "keypad", "GO TO THE KEYPAD"),
            step("enter_code", "keypad", "press it NOW", "4317"),
        ])
        review = audited([step("use", "keypad", "press it NOW", "4317")])
        result, _ = self.decide(text, draft, review,
                                prior_facts=[CODE_FACT], referent="keypad")
        self.assertEqual(result.actions, (
            {"action": "enter_code", "target": "keypad", "argument": "4317"},))

    def test_uploaded_open_unlocked_door_discards_invented_keypad_step(self):
        text = "Can you open the door now?"
        self.assertTrue(contains_explicit_action_request(text))
        draft = proposed("action", [], speech="The door is open already.")
        review = audited([
            step("use", "exit_door", "open the door"),
            step("use", "keypad", "Can you open the door now?", "1234"),
        ])
        result, backend = self.decide(text, draft, review, referent="keypad")
        self.assertEqual(result.actions, (
            {"action": "use", "target": "exit_door", "argument": ""},))
        self.assertEqual(backend.review_calls, 1)

    def test_try_open_door_requires_no_separate_move(self):
        text = "Try opening the door now."
        draft = proposed("action", [step("use", "exit_door",
                                          "opening the door", "open")],
                         speech="I'll try the door.")
        result, _ = self.decide(text, draft, audited([]))
        self.assertEqual(result.actions, (
            {"action": "use", "target": "exit_door", "argument": ""},))

    def test_polite_misclassified_request_can_recover_from_review(self):
        text = "Could you open the door now?"
        draft = proposed("conversation", [], "I don't know about that.")
        result, backend = self.decide(text, draft, audited(
            [step("use", "exit_door", "open the door")]))
        self.assertEqual(result.action, "use")
        self.assertEqual(result.target, "exit_door")
        self.assertEqual(backend.review_calls, 1)

    def test_no_observed_note_cannot_guess_code(self):
        with self.assertRaises(PlanRejected):
            validated_steps([step("enter_code", "keypad", "input that code", "4317")],
                            "input that code", room(), "keypad")
        result, _ = self.decide(
            "Enter the code into the keypad",
            proposed("action", [step("enter_code", "keypad",
                                     "Enter the code into the keypad", "4317")]),
            audited([]), referent="keypad")
        self.assertEqual(result.action, "wait")

    def test_unconfirmed_or_model_generated_note_cannot_authorize(self):
        for fact in ({**CODE_FACT, "success": False},
                     {"action": "survey", "target": "room", "success": True,
                      "description": CODE_FACT["description"]}):
            with self.subTest(fact=fact):
                result, _ = self.decide(
                    "Enter the code into the keypad",
                    proposed("action", [step("enter_code", "keypad",
                        "Enter the code into the keypad", "4317")]),
                    audited([]), prior_facts=[fact], referent="keypad")
                self.assertEqual(result.action, "wait")

    def test_explicit_other_code_is_not_overridden_by_note(self):
        with self.assertRaises(PlanRejected):
            validated_steps([step("enter_code", "keypad", "Enter 9999", "4317")],
                            "Enter 9999 into the keypad", room(),
                            "keypad", "4317")
        self.assertEqual(validated_steps([
            step("enter_code", "keypad", "Enter 9999", "9999")
        ], "Enter 9999 into the keypad", room(), "keypad", "4317")[0]["argument"],
                         "9999")

    def test_hypothetical_door_is_not_rescued_as_a_real_action(self):
        text = "What if you open the door now?"
        result, _ = self.decide(
            text, proposed("action", []),
            audited([step("use", "exit_door", "open the door")]))
        self.assertEqual(result.actions, ())

    def test_compound_invalid_review_still_fails_closed(self):
        text = "Open the door and then enter 9999 in the keypad."
        result, _ = self.decide(
            text, proposed("action", [step("use", "exit_door", "Open the door")]),
            audited([step("use", "exit_door", "Open the door"),
                     step("use", "keypad", "enter 9999 in the keypad", "1234")]))
        self.assertEqual(result.actions, ())

    def test_explanation_question_does_not_open_door(self):
        question = "Would you tell me how to open the door?"
        with self.assertRaises(PlanRejected):
            validated_steps([step("use", "exit_door", "open the door")],
                            question, room())
        result, _ = self.decide(
            question,
            proposed("action", []),
            audited([step("use", "exit_door", "open the door")]))
        self.assertEqual(result.actions, ())

    def test_polite_try_opening_is_an_action_request(self):
        request = "Can you try opening the door now?"
        self.assertTrue(contains_explicit_action_request(request))
        result, backend = self.decide(
            request, proposed("conversation", [], "Maybe it is possible."),
            audited([step("use", "exit_door", "opening the door")]))
        self.assertEqual(result.action, "use")
        self.assertEqual(result.target, "exit_door")
        self.assertEqual(backend.review_calls, 1)

    def test_false_open_claim_stripped_when_only_unlocked(self):
        current = room()
        current["door_unlocked"] = True
        current["escaped"] = False
        state = {"history": [], "facts": []}
        answer = Agent._ground_dialogue(
            "The door is open now. The keypad is green.", current, state,
            "Can you open the door now?", allow_fallback=False)
        self.assertNotIn("door is open", answer.lower())
        self.assertIn("keypad is green", answer.lower())
        self.assertEqual(Agent._ground_verified_outcome(
            "I opened the door.", "enter_code", "keypad", True,
            "The keypad accepted the code. The door unlocked.", current), "")


if __name__ == "__main__":
    unittest.main()
