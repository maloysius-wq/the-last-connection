"""Local HTTP API. Run: python -m ai_bridge.server [--mock]. No third-party packages."""
from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time
from pathlib import Path

from .agent import Agent, AgentError, BackendUnavailable, InvalidRequest, MockBackend, OllamaBackend, SessionStore, MODEL
from .voice import LocalVoiceService, VoiceError, VoiceUnavailable, MAX_WAV_BYTES
from .session_export import build_session_archive
from .voice_prefetch import VoicePrefetch

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 16_384


def create_handler(agent: Agent, mode: str, updater=None,
                   voice: LocalVoiceService | None = None):
    prefetch = VoicePrefetch(voice)
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_wav(self, pcm_wav: bytes, engine=""):
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            if engine in ("native", "native_vulkan", "nano", "nano_cuda", "piper"):
                self.send_header("X-TLC-Voice-Engine", engine)
            self.send_header("Content-Length", str(len(pcm_wav)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(pcm_wav)

        def _send_zip(self, payload: bytes):
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="TheLastConnection-Session.zip"')
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _read_voice_json(self, maximum: int) -> dict:
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                raise InvalidRequest("Voice requests require application/json.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= maximum:
                raise InvalidRequest("Voice request is empty or too large.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise InvalidRequest("Voice request must contain a JSON object.")
            return payload

        def do_GET(self):
            if self.path == "/api/update/check" and updater is not None:
                try:
                    return self._send(200, updater.check())
                except Exception as exc:
                    # Update checks never interrupt AI gameplay.
                    return self._send(503, {"error": str(exc)[:300]})
            if self.path == "/api/voice/status":
                return self._send(200, voice.status() if voice is not None else {
                    "stt_ready": False, "tts_ready": False, "offline": True,
                    "push_to_talk": "hold_v",
                })
            if self.path == "/api/health":
                ready = voice.status() if voice is not None else {}
                return self._send(200, {"ok": True, "backend": mode,
                    "model": MODEL if mode == "ollama" else "mock",
                    "voice_ready": bool(ready.get("stt_ready") and ready.get("tts_ready"))})
            return self._send(404, {"error": "Not found"})

        def do_POST(self):
            if self.path == "/api/session/export":
                if (self.headers.get("X-TLC-Export") != "1" or
                        self.headers.get("Content-Type", "").split(";")[0].strip().lower()
                        != "application/json"):
                    return self._send(403, {"error": "Export requires an explicit in-game request."})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 900_000:
                        raise InvalidRequest("Conversation export request is too large.")
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise InvalidRequest("Invalid session export request.")
                    archive = build_session_archive(
                        agent.store, data.get("session_id", ""),
                        data.get("transcript", ""), data.get("world", {}))
                    return self._send_zip(archive)
                except (InvalidRequest, ValueError, TypeError, json.JSONDecodeError) as exc:
                    return self._send(400, {"error": str(exc)[:220]})
                except (OSError, RuntimeError):
                    return self._send(503, {"error": "Local conversation export couldn't be created."})
            if self.path in ("/api/voice/transcribe", "/api/voice/speak", "/api/voice/warmup"):
                if voice is None:
                    return self._send(503, {"error": "Optional voice runtime is not installed. Text mode still works."})
                try:
                    if self.path == "/api/voice/transcribe":
                        data = self._read_voice_json(8_100_000)
                        encoded = data.get("wav_b64", "")
                        if not isinstance(encoded, str) or len(encoded) > 8_000_000:
                            raise VoiceError("Microphone recording is too large.")
                        try:
                            wav = base64.b64decode(encoded, validate=True)
                        except (ValueError, binascii.Error) as exc:
                            raise VoiceError("Invalid microphone audio encoding.") from exc
                        if len(wav) > MAX_WAV_BYTES:
                            raise VoiceError("Microphone recording is too large.")
                        transcript = voice.transcribe(wav, data.get("sensitivity", 0.20))
                        return self._send(200, {"transcript": transcript})
                    data = self._read_voice_json(2_000)
                    options = {key: data[key] for key in ("profile", "threads", "engine") if key in data}
                    if self.path == "/api/voice/warmup":
                        # Preflight only the selected persistent engine. Never
                        # synthesize a discarded fallback or poison gameplay.
                        started = time.monotonic()
                        try:
                            with prefetch.synthesis_lock:
                                voice.synthesize("I'm listening.", "calm", warmup_only=True, **options)
                        except VoiceUnavailable as exc:
                            return self._send(200, {"status": "deferred", "reason": str(exc),
                                "seconds": round(time.monotonic() - started, 3)})
                        return self._send(200, {"status": "ready",
                            "engine": getattr(voice, "last_engine", ""),
                            "seconds": round(time.monotonic() - started, 3)})
                    audio = prefetch.take(data.get("prefetch_id"), data.get("text", ""),
                                          data.get("emotion", "calm"), options)
                    if audio is not None:
                        print("[Voice] Consumed validated streamed speech prefetch")
                        return self._send_wav(audio, "nano_cuda")
                    with prefetch.synthesis_lock:
                        audio = voice.synthesize(data.get("text", ""), data.get("emotion", "calm"), **options)
                        engine = getattr(voice, "last_engine", "")
                    return self._send_wav(audio, engine)
                except VoiceUnavailable as exc:
                    return self._send(503, {"error": str(exc)})
                except (VoiceError, InvalidRequest, ValueError, TypeError, json.JSONDecodeError) as exc:
                    return self._send(400, {"error": str(exc)})
                except Exception:
                    # Do not spill paths or microphone buffers through HTTP.
                    return self._send(503, {"error": "Local voice processing failed. Text mode is available."})
            if self.path == "/api/update/request":
                if updater is None:
                    return self._send(404, {"error": "Updater is only available in the portable game."})
                # Custom header + JSON cannot be sent as a browser simple request.
                # Cross-origin preflight is intentionally unsupported on localhost.
                if (self.headers.get("X-TLC-Update") != "1" or
                        self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json"):
                    return self._send(403, {"error": "Update request must originate from the game."})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 2048:
                        raise InvalidRequest("Invalid update request size")
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict) or data.get("confirm") is not True:
                        return self._send(403, {"error": "Update requires explicit player confirmation."})
                    return self._send(200, updater.queue(data.get("tag", "")))
                except (ValueError, TypeError, InvalidRequest) as exc:
                    return self._send(400, {"error": str(exc)})
                except Exception as exc:
                    return self._send(503, {"error": str(exc)[:300]})
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
                ticket = None
                if self.path == "/api/decide":
                    options = data.get("voice_prefetch")
                    if isinstance(options, dict) and mode == "llama.cpp":
                        def offer(speech, emotion):
                            nonlocal ticket
                            if ticket is None:
                                ticket = prefetch.offer(speech, emotion, options)
                        result = agent.decide(sid, data.get("player_text", ""), data.get("world"),
                                              on_speech=offer)
                    else:
                        result = agent.decide(sid, data.get("player_text", ""), data.get("world"))
                else:
                    result = agent.outcome(sid, data.get("action"), data.get("target", ""),
                                           data.get("success"), data.get("description", ""), data.get("world"),
                                           speak=data.get("speak", True))
                payload = asdict(result)
                approved = prefetch.approve(ticket, result)
                if approved:
                    payload["voice_prefetch_id"] = approved
                return self._send(200, payload)
            except (InvalidRequest, json.JSONDecodeError, ValueError, TypeError) as exc:
                return self._send(400, {"error": str(exc)})
            except BackendUnavailable as exc:
                hint = ("The local model produced invalid output twice. Try your message again."
                        if exc.category == "invalid_json" else
                        "Check the local dialogue server. Restart the game if it is no longer running.")
                if mode == "ollama" and exc.category != "invalid_json":
                    hint = "Check that Ollama and the configured model are running."
                return self._send(503, {"error": str(exc), "category": exc.category, "hint": hint})
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
