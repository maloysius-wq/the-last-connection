"""Portable setup, location and local llama.cpp transport tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from io import BytesIO
import json
import unittest

from ai_bridge.agent import BackendUnavailable, LlamaCppBackend
from portable.launcher import PortableSetupError, find_gguf_candidates, select_model, warm_dialogue


class FakeHTTPResponse:
    status = 200
    def __init__(self, value):
        self.data = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=1000000):
        return self.data[:limit]


class TestPortable(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "models").mkdir()
        self.gguf = self.root / "models" / "qwen3-4b-instruct.gguf"
        self.gguf.write_bytes(b"GGUF")

    def tearDown(self):
        self.tmp.cleanup()

    def test_uses_in_place_gguf_without_copy(self):
        path = select_model(self.root, {})
        self.assertEqual(path, self.gguf.resolve())
        self.assertEqual(self.gguf.read_bytes(), b"GGUF")

    def test_configured_model_path_preferred(self):
        other = self.root / "other.gguf"
        other.write_bytes(b"GGUF2")
        self.assertEqual(select_model(self.root, {"model_path": str(other)}), other.resolve())

    def test_missing_configured_model_fails_explicitly(self):
        with self.assertRaises(PortableSetupError):
            select_model(self.root, {"model_path": str(self.root / "gone.gguf")})

    def test_ambiguous_gguf_asks_instead_of_guessing(self):
        other = self.root / "models" / "other.gguf"
        other.write_bytes(b"GGUF2")
        with self.assertRaises(PortableSetupError):
            select_model(self.root, {})
        self.assertEqual(select_model(self.root, {}, chooser=lambda: str(other)), other.resolve())

    def test_multiple_roots_are_discovered(self):
        external = self.root / "LocalForge" / "deep"
        external.mkdir(parents=True)
        source = external / "eli.gguf"
        source.write_bytes(b"GGUF3")
        items = find_gguf_candidates(self.root, (external,))
        self.assertEqual(set(items), {self.gguf.resolve(), source.resolve()})

    def test_llama_cpp_json_schema_response(self):
        result = {"speech": "I'll take it.", "action": "take", "target": "flashlight", "argument": "", "emotion": "curious"}
        fake = FakeHTTPResponse({"choices": [{"message": {"content": json.dumps(result)}}]})
        with patch("ai_bridge.agent.request.urlopen", return_value=fake) as mocked:
            decision = LlamaCppBackend().respond([{"role": "user", "content": "Grab the flashlight"}])
        self.assertEqual(decision, result)
        req = mocked.call_args[0][0]
        body = json.loads(req.data)
        self.assertEqual(body["model"], "tlc-eli")
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertIn("argument", body["response_format"]["schema"]["properties"])
        self.assertEqual(req.full_url, "http://127.0.0.1:8877/v1/chat/completions")

    def test_startup_warmup_generates_only_two_local_tokens(self):
        reply = FakeHTTPResponse({"choices": [{"message": {"content": "ready"}}],
                                  "usage": {"completion_tokens": 1}})
        with patch("portable.launcher.request.urlopen", return_value=reply) as mocked:
            result = warm_dialogue()
        self.assertEqual(result["status"], "ready")
        req = mocked.call_args.args[0]
        body = json.loads(req.data)
        self.assertEqual(req.full_url, "http://127.0.0.1:8877/v1/chat/completions")
        self.assertEqual(body["max_tokens"], 2)
        self.assertFalse(body["cache_prompt"])
        self.assertNotIn("session_id", body)
        self.assertEqual(mocked.call_args.kwargs["timeout"], 20)

    def test_startup_warmup_failures_are_nonfatal_and_not_reported_ready(self):
        for reply in (FakeHTTPResponse({"choices": [{}], "usage": {"completion_tokens": 0}}),
                      FakeHTTPResponse({"error": "model unavailable"})):
            with patch("portable.launcher.request.urlopen", return_value=reply):
                self.assertEqual(warm_dialogue()["status"], "failed")
        with patch("portable.launcher.request.urlopen", side_effect=TimeoutError):
            self.assertEqual(warm_dialogue()["status"], "failed")

    def test_llama_cpp_invalid_response_fails_without_fake_success(self):
        fake = FakeHTTPResponse({"choices": [{"message": {"content": "not json"}}]})
        with patch("ai_bridge.agent.request.urlopen", return_value=fake):
            with self.assertRaises(BackendUnavailable):
                LlamaCppBackend().respond([{"role": "user", "content": "Hello"}])


if __name__ == "__main__":
    unittest.main()
