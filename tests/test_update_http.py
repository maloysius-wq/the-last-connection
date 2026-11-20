"""The update button's bridge only accepts explicitly confirmed local actions."""
import json
from threading import Thread
import unittest
from http.server import ThreadingHTTPServer
from urllib import request, error

from ai_bridge.server import create_handler


class UpdateProvider:
    def __init__(self):
        self.checked = 0
        self.queued = []
    def check(self):
        self.checked += 1
        return {"available": True, "latest": "portable-" + "1"*40,
                "current": "legacy", "title": "Game update", "size": 123}
    def queue(self, tag):
        self.queued.append(tag)
        return {"ok": True}


class TestUpdateHTTP(unittest.TestCase):
    def setUp(self):
        self.provider = UpdateProvider()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0),
            create_handler(None, "llama.cpp", updater=self.provider))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_check_only_does_not_queue_install(self):
        with request.urlopen(self.base+"/api/update/check") as res:
            state = json.load(res)
        self.assertTrue(state["available"])
        self.assertEqual(self.provider.checked, 1)
        self.assertEqual(self.provider.queued, [])

    def test_install_requires_explicit_confirm_and_custom_header(self):
        tag = "portable-" + "1" * 40
        for headers, body in [({}, {"tag": tag, "confirm": True}),
                              ({"X-TLC-Update": "1"}, {"tag": tag, "confirm": False})]:
            req = request.Request(self.base+"/api/update/request", data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", **headers}, method="POST")
            with self.assertRaises(error.HTTPError) as err:
                request.urlopen(req)
            self.assertEqual(err.exception.code, 403)
        self.assertEqual(self.provider.queued, [])
        req = request.Request(self.base+"/api/update/request", data=json.dumps({"tag": tag, "confirm": True}).encode(),
            headers={"Content-Type": "application/json", "X-TLC-Update": "1"}, method="POST")
        with request.urlopen(req) as res:
            self.assertTrue(json.load(res)["ok"])
        self.assertEqual(self.provider.queued, [tag])


if __name__ == "__main__":
    unittest.main()
