"""Local HTTP API. Run: python -m ai_bridge.server [--mock]. No third-party packages."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

from .agent import Agent, AgentError, BackendUnavailable, InvalidRequest, MockBackend, OllamaBackend, SessionStore, MODEL

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 16_384


def create_handler(agent: Agent, mode: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/health":
                return self._send(200, {"ok": True, "backend": mode, "model": MODEL if mode == "ollama" else ("tlc-eli" if mode == "llama.cpp" else "mock"), "voice_ready": False})
            return self._send(404, {"error": "Not found"})

        def do_POST(self):
            if self.path not in ("/api/decide", "/api/outcome"):
                return self._send(404, {"error": "Not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    raise InvalidRequest("Invalid request size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise InvalidRequest("Expected an object")
                sid = data.get("session_id", "")
                if self.path == "/api/decide":
                    result = agent.decide(sid, data.get("player_text", ""), data.get("world"))
                else:
                    result = agent.outcome(sid, data.get("action"), data.get("target", ""),
                                           data.get("success"), data.get("description", ""), data.get("world"))
                return self._send(200, asdict(result))
            except (InvalidRequest, json.JSONDecodeError, ValueError, TypeError) as exc:
                return self._send(400, {"error": str(exc)})
            except BackendUnavailable as exc:
                return self._send(503, {"error": str(exc), "hint": "Start Ollama and pull the configured model, or use --mock for a scripted test."})
            except AgentError as exc:
                return self._send(500, {"error": str(exc)})

        def log_message(self, format, *args):
            print("[AI Bridge]", format % args)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="The Last Connection local AI bridge")
    parser.add_argument("--mock", action="store_true", help="Use a clearly scripted backend, no LLM required")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    backend = MockBackend() if args.mock else OllamaBackend()
    agent = Agent(backend, SessionStore(), ROOT / "data" / "characters" / "eli.json")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), create_handler(agent, "mock" if args.mock else "ollama"))
    print(f"AI bridge on http://127.0.0.1:{args.port} ({'mock' if args.mock else 'ollama'} mode)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
