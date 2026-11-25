"""Regression from session 1795629599: remote perspective, looping, 503."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import URLError

from ai_bridge.agent import Agent, BackendUnavailable, LlamaCppBackend, SessionStore
from test_emotional_relationship import Model, plan, appraisal, PERSONA
from test_semantic_planner import world
from test_dialogue_backends import Reply

FIRST = "You say you're stuck too? And you see me on a screen? That's not possible—there's no screen in this room, and I don't see anything like that. If you're claiming to see me, then either you're lying, or you're not actually in the same place. And if you're not, then how do you know what I'm doing? I don't have a screen. I don't have a camera."
LOOP = "You say you can see me on a camera, but I don't see anything. There's no screen, no feed, no visible camera in this room. If you're claiming to see me, then either you're lying or you're not actually in the same place. And if you're not, then how do you know what I'm doing? I don't have a camera."
PLAYER = "No I'm not in that room at all. I am watching you on a screen from a control room that I woke up in."
FALSE_BOUNDARY = "You claim to see me on a screen, but I have no evidence of such a device or feed. I will not accept this as fact without"


class ConversationLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def seed(self):
        self.store.save("loop", {"history": [
            {"role": "user", "content": "I can see you on a screen in my room."},
            {"role": "assistant", "content": FIRST},
            {"role": "user", "content": "I am in another room."},
            {"role": "assistant", "content": LOOP},
        ], "facts": [], "relationship": {"trust": -75, "stress": 100, "anger": 87, "turns": 4,
                                          "boundaries": [FALSE_BOUNDARY, "Refuses to describe the monitor"]}})

    def test_loop_repair_keeps_distrust_and_no_actions(self):
        self.seed()
        model = Model(plan(LOOP, emotion="angry", social=appraisal(trust=-2, anger=2, boundary=FALSE_BOUNDARY)),
                      reaction="So the screen is in your room. Fine. That doesn't mean I trust whoever put us here.")
        agent = Agent(model, self.store, PERSONA)
        result = agent.decide("loop", PLAYER, world())
        self.assertEqual(result.actions, ())
        self.assertEqual(result.emotion, "angry")
        self.assertIn("screen is in your room", result.speech)
        self.assertEqual(len(model.requests), 1)
        self.assertEqual(len(model.reactions), 1)
        self.assertIn("CONVERSATION REPAIR", model.reactions[0][0]["content"])
        self.assertEqual(model.reactions[0][-1]["content"], PLAYER)
        saved = self.store.load("loop")
        self.assertEqual(saved["relationship"]["trust"], -75)
        self.assertEqual(saved["relationship"]["anger"], 87)
        self.assertEqual(saved["relationship"]["boundaries"], ["Refuses to describe the monitor"])

    def test_first_contact_remains_uncertain_and_fresh_chat_one_call(self):
        model = Model(plan("Wait, you're saying you're trapped somewhere else too?"))
        agent = Agent(model, self.store, PERSONA)
        result = agent.decide("fresh", PLAYER, world())
        self.assertIn("somewhere else", result.speech)
        self.assertEqual(len(model.reactions), 0)
        system = model.requests[0][0]["content"]
        self.assertIn("unknown, do not assume a camera feed", system)
        self.assertIn("screen in ANOTHER room", system)
        self.assertIn("Understand a claim BEFORE", system)

    def test_failed_repair_does_not_repeat_or_act(self):
        self.seed()
        model = Model(plan(LOOP), reaction=LOOP)
        result = Agent(model, self.store, PERSONA).decide("loop", PLAYER, world())
        self.assertFalse(result.speech)
        self.assertFalse(result.actions)
        self.assertIn("No action", result.status)

    def test_explicit_player_boundary_survives_false_eli_boundary(self):
        model = Model(plan("I don't believe you.", social=appraisal(boundary=FALSE_BOUNDARY)),
                      plan("All right, I won't ask.", social=appraisal(boundary="Refuses to describe the monitor")))
        agent = Agent(model, self.store, PERSONA)
        agent.decide("boundaries", PLAYER, world())
        agent.decide("boundaries", "I will never tell you what I see on the monitor.", world())
        self.assertEqual(self.store.load("boundaries")["relationship"]["boundaries"], ["Refuses to describe the monitor"])

    def test_malformed_output_retries_once_without_partial_actions(self):
        valid = plan("I hear you.")
        calls = []
        def fetch(req, timeout):
            calls.append(json.loads(req.data))
            content = '{"kind":"action","goals":[' if len(calls) == 1 else json.dumps(valid)
            return Reply({"choices": [{"finish_reason": "length" if len(calls) == 1 else "stop", "message": {"content": content}}]})
        with patch("ai_bridge.agent.request.urlopen", side_effect=fetch):
            answer = Agent(LlamaCppBackend(), self.store, PERSONA).decide("retry", PLAYER, world())
        self.assertEqual(len(calls), 2)
        self.assertEqual(answer.actions, ())
        self.assertEqual(answer.speech, "I hear you.")
        self.assertEqual(calls[1]["messages"][-1]["content"], PLAYER)

    def test_transport_failure_traced_and_not_retried(self):
        self.seed()
        old = self.store.load("loop")
        with patch("ai_bridge.agent.request.urlopen", side_effect=URLError("connection reset")) as fetch:
            with self.assertRaises(BackendUnavailable) as caught:
                Agent(LlamaCppBackend(), self.store, PERSONA).decide("loop", PLAYER, world())
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(caught.exception.category, "transport")
        self.assertEqual(self.store.load("loop"), old)
        records = [json.loads(line) for line in self.store.trace_path("loop").read_text().splitlines()]
        self.assertEqual(records[-1]["kind"], "goal_model_error")
        self.assertEqual(records[-1]["details"]["category"], "transport")

    def test_malformed_response_twice_has_specific_diagnostics(self):
        response = {"choices": [{"finish_reason": "length", "message": {"content": "{"}}]}
        with patch("ai_bridge.agent.request.urlopen", side_effect=lambda *a, **k: Reply(response)) as fetch:
            with self.assertRaises(BackendUnavailable) as caught:
                Agent(LlamaCppBackend(), self.store, PERSONA).decide("bad", PLAYER, world())
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(caught.exception.category, "invalid_json")
        self.assertIn("finish_reason=length", caught.exception.detail)
        self.assertFalse(self.store.load("bad")["history"])
