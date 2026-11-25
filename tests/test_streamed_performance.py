"""Portable compact wire, cache and streamed speech safety regression tests."""
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from ai_bridge.agent import LlamaCppBackend, _completed_json_fields, BackendUnavailable
from ai_bridge.goals import expand_compact_goal, COMPACT_GOAL_SCHEMA, GOAL_SCHEMA
from ai_bridge.voice_prefetch import VoicePrefetch, first_voice_chunk

RAW = {"e": "cautious", "s": "Who are you?", "k": "conversation", "g": [],
       "a": {"t": 0, "s": 0, "a": 0, "w": "consider", "m": "none", "p": "unchanged", "b": ""}}
OPTIONS = {"engine": "nano_cuda", "profile": "default", "threads": 0}
MESSAGES = [{"role": "system", "content": "Stable prompt"}, {"role": "user", "content": "Hello"}]


def sse(raw=RAW, done=True):
    text = json.dumps(raw, separators=(",", ":"))
    events = [("data: " + json.dumps({"choices": [{"delta": {"content": c}, "finish_reason": None}]}) + "\n\n").encode()
              for c in text]
    events.append(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n')
    if done:
        events.append(b"data: [DONE]\n\n")
    return io.BytesIO(b"".join(events))


class PerformanceTests(unittest.TestCase):
    def test_compact_expansion_preserves_all_canonical_fields(self):
        raw = dict(RAW, g=[{"a": "enter_code", "t": "keypad", "v": "1234"}])
        parsed = expand_compact_goal(raw)
        self.assertEqual(set(parsed), set(GOAL_SCHEMA["required"]))
        self.assertEqual(parsed["goals"], [{"action": "enter_code", "target": "keypad", "argument": "1234"}])
        self.assertEqual(parsed["appraisal"]["willingness"], "consider")
        with self.assertRaises(ValueError):
            expand_compact_goal(dict(raw, extra=1))

    def test_stream_offers_completed_speech_before_final_json(self):
        events = []
        with patch("ai_bridge.agent.request.urlopen", return_value=sse()) as fetch:
            result = LlamaCppBackend(compact=True).plan_goals(MESSAGES, on_speech=lambda s,e: events.append((s,e)))
        self.assertEqual(events, [("Who are you?", "cautious")])
        self.assertEqual(result["speech"], "Who are you?")
        body = json.loads(fetch.call_args.args[0].data)
        self.assertTrue(body["stream"])
        self.assertTrue(body["cache_prompt"])
        self.assertEqual(body["n_cache_reuse"], 64)
        self.assertEqual(body["response_format"]["schema"], COMPACT_GOAL_SCHEMA)
        self.assertEqual(body["messages"][-1], MESSAGES[-1])
        self.assertIn("OUTPUT FORMAT", body["messages"][0]["content"])

    def test_invalid_stream_retries_without_exposing_partial_goals(self):
        answer = io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(RAW)}, "finish_reason": "stop"}]}).encode())
        with patch("ai_bridge.agent.request.urlopen", side_effect=[sse(done=False), answer]) as fetch:
            result = LlamaCppBackend(compact=True).plan_goals(MESSAGES)
        self.assertEqual(result["goals"], [])
        self.assertFalse(json.loads(fetch.call_args.args[0].data)["stream"])

    def test_partial_json_cannot_invent_speech_field_from_escaped_text(self):
        self.assertEqual(_completed_json_fields('{"e":"calm","s":"unfinished'), {"e": "calm"})
        self.assertEqual(_completed_json_fields(json.dumps({"e":"calm","s":'He said "hello"'}))["s"], 'He said "hello"')

    def test_prefetch_requires_matching_validated_reply_and_is_one_use(self):
        voice = Mock()
        voice.startup_report = {"status":"ready","engine":"nano_cuda","settings":OPTIONS}
        voice.last_engine = "nano_cuda"
        voice.synthesize.return_value = b"audio"
        p = VoicePrefetch(voice)
        ticket = p.offer("Who are you? Tell me.", "cautious", dict(OPTIONS, fast=True))
        self.assertTrue(ticket)
        self.assertIsNone(p.take(ticket, "Who are you?", "cautious", OPTIONS))
        decision = SimpleNamespace(actions=(), status="", emotion="cautious", speech="Who are you? Tell me.")
        self.assertEqual(p.approve(ticket, decision), ticket)
        self.assertEqual(p.take(ticket, "Who are you?", "cautious", OPTIONS), b"audio")
        self.assertIsNone(p.take(ticket, "Who are you?", "cautious", OPTIONS))
        voice.synthesize.assert_called_once_with("Who are you?", "cautious", warmup_only=True, **OPTIONS)

    def test_prefetch_rejected_draft_and_changed_profile_never_play(self):
        voice = Mock()
        voice.startup_report = {"status":"ready","engine":"nano_cuda","settings":OPTIONS}
        voice.last_engine = "nano_cuda"
        voice.synthesize.return_value = b"audio"
        p = VoicePrefetch(voice)
        self.assertIsNone(p.offer("Hello.", "calm", dict(OPTIONS, profile="joe", fast=True)))
        ticket = p.offer("Wrong draft.", "calm", dict(OPTIONS, fast=True))
        decision = SimpleNamespace(actions=(), status="", emotion="calm", speech="Different reply.")
        self.assertFalse(p.approve(ticket, decision))
        self.assertIsNone(p.take(ticket, "Wrong draft.", "calm", OPTIONS))
        self.assertEqual(first_voice_chunk("First sentence. Next sentence."), "First sentence.")
        self.assertEqual(first_voice_chunk("First sentence. Next sentence.", False), "First sentence. Next sentence.")
