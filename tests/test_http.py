import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib import request, error

from ai_bridge.agent import Agent, MockBackend, SessionStore
from ai_bridge.server import create_handler

ROOT = Path(__file__).resolve().parents[1]
WORLD = {
    "room": "maintenance_chamber", "inventory": [],
    "objects": {"flashlight": {"visible": True, "can_take": True,
                              "description": "Flashlight on a desk"}}
}

class TestBridgeHTTP(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        agent = Agent(MockBackend(), SessionStore(Path(self.tempdir.name)),
                      ROOT / "data/characters/eli.json")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(agent, "mock"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tempdir.cleanup()

    def post(self, path, body):
        req = request.Request(self.url + path, json.dumps(body).encode("utf-8"),
                              {"Content-Type": "application/json"}, method="POST")
        with request.urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read())

    def test_full_instruction_and_outcome(self):
        status, decision = self.post("/api/decide", {
            "session_id": "http_test", "player_text": "Pick up the flashlight", "world": WORLD})
        self.assertEqual(status, 200)
        self.assertEqual(decision["action"], "take")
        self.assertEqual(decision["target"], "flashlight")
        inventory_world = {**WORLD, "inventory": ["flashlight"]}
        status, outcome = self.post("/api/outcome", {
            "session_id": "http_test", "action": "take", "target": "flashlight",
            "success": True, "description": "Eli picked up the flashlight", "world": inventory_world})
        self.assertEqual(status, 200)
        self.assertEqual(outcome["action"], "wait")
        status, memory = self.post("/api/decide", {
            "session_id": "http_test", "player_text": "What are you holding?", "world": inventory_world})
        self.assertIn("flashlight", memory["speech"].lower())

    def test_health(self):
        with request.urlopen(self.url + "/api/health", timeout=5) as res:
            health = json.loads(res.read())
        self.assertEqual(health["backend"], "mock")
        self.assertFalse(health["voice_ready"])

    def test_bad_request(self):
        with self.assertRaises(error.HTTPError) as err:
            self.post("/api/decide", {"session_id": "../bad", "player_text": "x", "world": WORLD})
        self.assertEqual(err.exception.code, 400)

    def test_unsupported_path(self):
        with self.assertRaises(error.HTTPError) as err:
            self.post("/api/unknown", {})
        self.assertEqual(err.exception.code, 404)

if __name__ == "__main__":
    unittest.main()
