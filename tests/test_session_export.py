"""Session ZIP is a local player-initiated export, never an automatic upload."""
import io
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib import request, error
import unittest
import zipfile

from ai_bridge.agent import Agent, InvalidRequest, MockBackend, SessionStore
from ai_bridge.server import create_handler
from ai_bridge.session_export import build_session_archive

PERSONA = Path(__file__).resolve().parents[1] / "data/characters/eli.json"


class TestSessionExport(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = SessionStore(Path(self.tmp.name))
        self.store.save("eli_safe", {"history": [
            {"role": "user", "content": "Try dancing in the corner."},
            {"role": "assistant", "content": "I can try, but why?"}
        ], "facts": []})
        self.store.trace("eli_safe", "model_interpretation", {"proposal":
                         {"kind": "action", "steps": [{
                             "action": "experiment", "target": "room",
                             "argument": "dance in place"}]}})
        self.store.trace("eli_safe", "godot_action_outcome", {"success": True,
                         "description": "Eli tried dancing, with no new mechanisms."})
        self.store.save("someone_else", {"history": [
            {"role": "user", "content": "PRIVATE OTHER PLAYER"}], "facts": []})
        self.store.trace("someone_else", "private", {"secret": "PRIVATE OTHER PLAYER"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_zip_contains_full_visible_conversation_and_diagnostics(self):
        transcript = "[YOU] Try dancing in the corner.\n\n[ELI] I can try, but why?\n"
        raw = build_session_archive(self.store, "eli_safe", transcript,
                                    {"lights_on": False, "inventory": []})
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertEqual(set(z.namelist()), {
                "README.txt", "conversation.txt", "diagnostics.jsonl",
                "conversation_state.json", "current_room.json", "export_manifest.json"})
            self.assertEqual(z.read("conversation.txt").decode(), transcript)
            diagnostics = z.read("diagnostics.jsonl").decode()
            self.assertIn("model_interpretation", diagnostics)
            self.assertIn("godot_action_outcome", diagnostics)
            self.assertNotIn("PRIVATE OTHER PLAYER", diagnostics)
            self.assertEqual(json.loads(z.read("current_room.json"))["lights_on"], False)
            self.assertEqual(json.loads(z.read("export_manifest.json"))["session_id"],
                             "eli_safe")
            self.assertNotIn("PRIVATE OTHER PLAYER", raw.decode("latin1"))

    def test_rejects_path_traversal_and_excessive_messages(self):
        for sid in ("../../secrets", "../", "other.json", ""):
            with self.subTest(sid=sid), self.assertRaises(InvalidRequest):
                build_session_archive(self.store, sid, "Hi", {})
        with self.assertRaises(InvalidRequest):
            build_session_archive(self.store, "eli_safe", "x" * 500_001, {})

    def test_session_without_previous_trace_still_exports(self):
        raw = build_session_archive(self.store, "fresh", "new session", {})
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertEqual(z.read("diagnostics.jsonl"), b"")
            self.assertEqual(z.read("conversation.txt"), b"new session")

    def test_trace_is_local_bounded_and_valid_jsonl(self):
        for i in range(4):
            self.store.trace("eli_safe", "test", {"idx": i})
        lines = self.store.trace_path("eli_safe").read_text().splitlines()
        self.assertEqual(json.loads(lines[-1])["details"]["idx"], 3)
        self.assertLess(self.store.trace_path("eli_safe").stat().st_size, 2_000_000)

    def test_http_endpoint_requires_in_game_header(self):
        agent = Agent(MockBackend(), self.store, PERSONA)
        server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(agent, "mock"))
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/api/session/export"
            message = json.dumps({"session_id": "eli_safe",
                                  "transcript": "[YOU] Hello", "world": {}}).encode()
            req = request.Request(url, message, {"Content-Type": "application/json"},
                                  method="POST")
            with self.assertRaises(error.HTTPError) as caught:
                request.urlopen(req, timeout=3)
            self.assertEqual(caught.exception.code, 403)
            authorized = request.Request(url, message,
                         {"Content-Type": "application/json", "X-TLC-Export": "1"},
                         method="POST")
            with request.urlopen(authorized, timeout=3) as reply:
                self.assertEqual(reply.headers.get("Content-Type"), "application/zip")
                with zipfile.ZipFile(io.BytesIO(reply.read())) as zipped:
                    self.assertIn("[YOU] Hello", zipped.read("conversation.txt").decode())
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
