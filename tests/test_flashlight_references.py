"""Actual November 20 playtest: Eli talks about the flashlight and player says 'that'.

The model can emit persuasive physical narration without any Godot action.
The world state, not language, decides whether Eli picked up a prop.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_bridge.agent import Agent, SessionStore
from ai_bridge.intent import classify

PERSONA = Path(__file__).resolve().parents[1] / "data" / "characters" / "eli.json"


def room(*, holding=False, switched=False):
    return {
        "room": "maintenance_chamber", "actor_at": "breaker_box",
        "last_observation": "", "inventory": ["flashlight"] if holding else [],
        "flashlight_on": switched,
        "objects": {
            "flashlight": {"visible": True, "description":
                "The flashlight is in Eli's inventory."
                if holding else "A flashlight resting on Eli's desk."},
            "keypad": {"visible": True, "description": "A red keypad by the door."},
            "breaker_box": {"visible": True, "description": "A breaker box on the wall."},
        },
    }


class NarrativeBackend:
    def __init__(self, replies):
        self.replies = list(replies)
        self.conversations = 0
        self.decisions = 0

    def converse(self, messages):
        self.conversations += 1
        return self.replies.pop(0)

    def respond(self, messages):
        self.decisions += 1
        # Intentionally ignores the command and emits a malformed intention.
        return {"speech": "I grabbed it and pressed the button. Maybe it's dead.",
                "action": "wait", "target": "", "emotion": "curious"}


class TestFlashlightReferences(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = SessionStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, backend):
        return Agent(backend, self.store, PERSONA)

    def test_exact_followup_uses_eli_flashlight_and_godot_action(self):
        backend = NarrativeBackend([
            "The room's dark. The only light is the flashlight on the desk. "
            "Do you see it?"
        ])
        agent = self.agent(backend)
        first = agent.decide("screenshot", "I see you through the camera.", room())
        self.assertEqual(first.action, "wait")
        self.assertEqual(self.store.load("screenshot")["referent"], "flashlight")
        reply = agent.decide(
            "screenshot",
            "I'm able to see it. Please pick that up and turn it on.",
            room())
        self.assertEqual((reply.action, reply.target, reply.argument),
                         ("use", "flashlight", "on"))
        self.assertIn("I'll pick up the flashlight", reply.speech)
        self.assertNotIn("I grabbed", reply.speech)
        self.assertEqual(backend.conversations, 1)
        self.assertEqual(backend.decisions, 1)
        actual = room(holding=True, switched=True)
        actual["last_observation"] = "Eli picked up the flashlight from the desk and switched it on."
        acknowledgment = agent.outcome(
            "screenshot", "use", "flashlight", True, actual["last_observation"], actual)
        self.assertIn("picked it up", acknowledgment.speech)
        self.assertEqual(backend.conversations + backend.decisions, 2,
                         "No second model inference during Godot outcome")

    def test_upgrading_existing_session_resolves_last_saved_eli_reply(self):
        # Older versions only persisted history/focus and could leave the
        # focus on the breaker even after Eli described the flashlight.
        self.store.save("upgraded", {
            "focus": "breaker_box",
            "history": [
                {"role": "user", "content": "Can you see a light?"},
                {"role": "assistant", "content":
                    '{"speech":"There is a flashlight on the desk. Do you see it?",'
                    '"action":"wait","target":""}'},
            ],
            "facts": [],
        })
        backend = NarrativeBackend([])
        result = self.agent(backend).decide(
            "upgraded", "I can see it. Please pick that up and turn it on.", room())
        self.assertEqual((result.action, result.target, result.argument),
                         ("use", "flashlight", "on"))
        self.assertEqual(self.store.load("upgraded")["referent"], "flashlight")

    def test_upgrading_ambiguous_history_does_not_use_stale_focus(self):
        self.store.save("old_ambiguous", {
            "focus": "breaker_box",
            "history": [
                {"role": "assistant", "content":
                    '{"speech":"I can see the flashlight and keypad.","action":"wait"}'}
            ],
            "facts": [],
        })
        backend = NarrativeBackend(["I'm not sure which object you mean."])
        result = self.agent(backend).decide(
            "old_ambiguous", "Please pick that up and turn it on.", room())
        self.assertEqual(result.action, "wait")
        self.assertEqual(self.store.load("old_ambiguous")["referent"], "")

    def test_multiple_elis_objects_do_not_guess_which_that(self):
        backend = NarrativeBackend([
            "There is a flashlight near the desk and the keypad by the door.",
            "I will grab the flashlight, but I don't know where to start."
        ])
        agent = self.agent(backend)
        agent.decide("multi", "What objects in the room worry you most?", room())
        self.assertEqual(self.store.load("multi")["referent"], "")
        result = agent.decide("multi", "Please pick that up and turn it on.", room())
        self.assertEqual(result.action, "wait")
        self.assertIn("haven't picked it up", result.speech)

    def test_no_referent_no_spontaneous_interaction(self):
        backend = NarrativeBackend([
            "I'll grab the flashlight. (Pause) I pressed the switch and "
            "nothing happened. I'll keep it in my hand."
        ])
        result = self.agent(backend).decide(
            "new", "What do you think?", room())
        self.assertEqual(result.action, "wait")
        self.assertNotIn("I pressed", result.speech)
        self.assertNotIn("I'll grab", result.speech)
        self.assertIn("still on the desk", result.speech)
        self.assertEqual(self.store.load("new")["referent"], "flashlight")

    def test_fresh_session_no_action_is_implied(self):
        model = NarrativeBackend(["I'm not sure what to do."])
        agent = self.agent(model)
        result = agent.decide("fresh", "Pick it up and turn it on.", room())
        self.assertEqual(result.action, "wait")
        self.assertEqual(model.decisions, 0)
        self.assertEqual(model.conversations, 1)

    def test_explicit_flashlight_turn_on_still_works(self):
        self.assertEqual(
            (classify("Pick up the flashlight and turn it on").action,
             classify("Pick up the flashlight and turn it on").target,
             classify("Pick up the flashlight and turn it on").light_mode),
            ("use", "flashlight", "on"))

    def test_confirmed_outcome_sets_referent_for_next_instruction(self):
        agent = self.agent(NarrativeBackend([]))
        actual = room(holding=True, switched=False)
        agent.outcome("confirmed", "take", "flashlight", True,
                      "Eli picked up the flashlight.", actual)
        self.assertEqual(self.store.load("confirmed")["referent"], "flashlight")

    def test_unrelated_autobiography_does_not_trigger_claim_guard(self):
        backend = NarrativeBackend([
            "I took the bus to school every morning. I liked my old teachers."
        ])
        result = self.agent(backend).decide(
            "memory", "What do you remember about school?", room())
        self.assertIn("bus to school", result.speech)
        self.assertEqual(result.action, "wait")


if __name__ == "__main__":
    unittest.main()
