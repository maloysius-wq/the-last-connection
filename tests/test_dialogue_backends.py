"""Verify the real local HTTP backends use unstructured dialogue for conversation."""
import json
import unittest
from unittest.mock import patch

from ai_bridge.agent import LlamaCppBackend, OllamaBackend


class Reply:
    def __init__(self, payload):
        self.content = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=None):
        return self.content


class TestDialogueBackends(unittest.TestCase):
    def test_llama_cpp_dialogue_omits_json_schema(self):
        sent = []

        def responder(req, timeout):
            sent.append((json.loads(req.data), timeout))
            return Reply({"choices": [{"message": {"content": "I'm beside the breaker box."}}]})

        with patch("ai_bridge.agent.request.urlopen", side_effect=responder):
            answer = LlamaCppBackend().converse([
                {"role": "system", "content": "Be Eli"},
                {"role": "user", "content": "Where are you?"},
            ])
        self.assertEqual(answer, "I'm beside the breaker box.")
        payload, timeout = sent[0]
        self.assertNotIn("response_format", payload)
        self.assertIs(payload["stream"], False)
        self.assertIn("max_tokens", payload)
        self.assertEqual(timeout, 300)

    def test_ollama_dialogue_omits_json_constraint(self):
        sent = []

        def responder(req, timeout):
            sent.append((json.loads(req.data), timeout))
            return Reply({"message": {"content": "I'm worried, but I'm still here."}})

        with patch("ai_bridge.agent.request.urlopen", side_effect=responder):
            answer = OllamaBackend().converse([
                {"role": "system", "content": "Be Eli"},
                {"role": "user", "content": "How are you?"},
            ])
        self.assertEqual(answer, "I'm worried, but I'm still here.")
        payload, timeout = sent[0]
        self.assertNotIn("format", payload)
        self.assertIs(payload["think"], False)
        self.assertEqual(timeout, 90)


if __name__ == "__main__":
    unittest.main()
