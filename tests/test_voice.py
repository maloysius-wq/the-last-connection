"""Offline voice acceptance tests, without model files or microphone hardware."""
from __future__ import annotations

import base64
import io
import json
import math
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib import request, error
import unittest
import wave

from ai_bridge.agent import Agent, MockBackend, SessionStore
from ai_bridge.server import create_handler
from ai_bridge.voice import (
    LocalVoiceService, VoiceError, VoiceUnavailable, clean_transcript,
    normalize_wav, MAX_AUDIO_SECONDS,
)

ROOT = Path(__file__).resolve().parents[1]


def microphone_wav(rate=48000, channels=2, seconds=1.0, silent=False) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frame = bytearray()
        for index in range(int(seconds * rate)):
            value = 0 if silent else int(11000 * math.sin(2 * math.pi * 180 * index / rate))
            frame.extend(struct.pack("<h", value) * channels)
        wav.writeframes(bytes(frame))
    return out.getvalue()


class TestLocalVoice(unittest.TestCase):
    def test_48000_stereo_is_resampled_for_whisper(self):
        data = normalize_wav(microphone_wav())
        with wave.open(io.BytesIO(data), "rb") as stream:
            self.assertEqual(stream.getframerate(), 16000)
            self.assertEqual(stream.getnchannels(), 1)
            self.assertEqual(stream.getsampwidth(), 2)
            self.assertAlmostEqual(stream.getnframes() / 16000, 1.0, delta=.04)

    def test_silent_audio_does_not_become_a_hallucinated_instruction(self):
        with self.assertRaisesRegex(VoiceError, "clear voice"):
            normalize_wav(microphone_wav(silent=True))

    def test_bad_pcm_or_untrusted_audio_rejected(self):
        for bad in (b"junk", b"RIFF" + b"\x00" * 200):
            with self.subTest(bad=bad):
                with self.assertRaises(VoiceError):
                    normalize_wav(bad)

    def test_recording_duration_enforced(self):
        with self.assertRaisesRegex(VoiceError, "between"):
            normalize_wav(microphone_wav(seconds=0.1))
        with self.assertRaisesRegex(VoiceError, "too large"):
            normalize_wav(b"0" * 6_000_100)

    def test_recognizer_never_promotes_transcript_to_world_state(self):
        self.assertEqual(clean_transcript(" [00:00:00.000 --> 00:00:03.000]  Turn on the light!\n"),
                         "Turn on the light!")
        self.assertEqual(clean_transcript("[BLANK_AUDIO]"), "")
        self.assertEqual(clean_transcript(""), "")

    def test_missing_voice_is_optional_not_an_ai_startup_failure(self):
        with TemporaryDirectory() as temp:
            voice = LocalVoiceService(Path(temp))
            self.assertFalse(voice.status()["stt_ready"])
            self.assertFalse(voice.status()["tts_ready"])
            with self.assertRaises(VoiceUnavailable):
                voice.transcribe(microphone_wav())
            with self.assertRaises(VoiceUnavailable):
                voice.synthesize("Hello, this is Eli.")

    def test_transcribe_uses_local_pinned_runtime_and_removes_microphone_file(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            cli = base / "runtime/voice/whisper/whisper-cli.exe"
            model = cli.parent / "ggml-tiny.en-q5_1.bin"
            cli.parent.mkdir(parents=True)
            cli.write_bytes(b"MZ")
            model.write_bytes(b"model")
            calls = []
            def fake(args, **kwargs):
                calls.append((args, kwargs))
                target = Path(args[args.index("-of") + 1] + ".txt")
                target.write_text("Go grab the flashlight and turn it on.", encoding="utf-8")
                with wave.open(args[args.index("-f") + 1], "rb") as input_wav:
                    assert input_wav.getframerate() == 16000
                    assert input_wav.getnchannels() == 1
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            voice = LocalVoiceService(base, runner=fake)
            self.assertEqual(voice.transcribe(microphone_wav()),
                             "Go grab the flashlight and turn it on.")
            self.assertIn("-otxt", calls[0][0])
            self.assertIn("-nt", calls[0][0])
            self.assertFalse(list((base / "temp").iterdir()),
                             "Microphone samples must be deleted after transcription.")

    def test_tts_uses_piper_and_deletes_temporary_speech(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            folder = base / "runtime/voice/piper"
            folder.mkdir(parents=True)
            for name in ("piper.exe", "en_US-joe-medium.onnx", "en_US-joe-medium.onnx.json"):
                (folder / name).write_bytes(b"test asset")
            calls = []
            def fake(args, **kwargs):
                calls.append((args, kwargs))
                path = Path(args[args.index("--output_file") + 1])
                path.write_bytes(microphone_wav(rate=22050, channels=1, seconds=.5))
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            voice = LocalVoiceService(base, runner=fake)
            result = voice.synthesize("No, I don't trust you. What is this place?")
            self.assertTrue(result.startswith(b"RIFF"))
            self.assertIn("No, I don't trust", calls[0][1]["input"])
            self.assertEqual(Path(calls[0][0][0]), folder / "piper.exe")
            self.assertFalse(list((base / "temp").iterdir()))

    def test_tts_cannot_receive_unbounded_instructions(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp) / "runtime/voice/piper"
            folder.mkdir(parents=True)
            for name in ("piper.exe", "en_US-joe-medium.onnx", "en_US-joe-medium.onnx.json"):
                (folder / name).write_bytes(b"test asset")
            voice = LocalVoiceService(Path(temp))
            with self.assertRaisesRegex(VoiceError, "too long"):
                voice.synthesize("x" * 10000)


class FakeVoice:
    def status(self):
        return {"stt_ready": True, "tts_ready": True,
                "offline": True, "push_to_talk": "hold_v"}
    def transcribe(self, wav, sensitivity):
        if not wav.startswith(b"RIFF"):
            raise VoiceError("Invalid microphone WAV")
        return "Please check the door."
    def synthesize(self, spoken):
        if spoken != "I'm listening.":
            raise VoiceError("Bad text")
        return microphone_wav(rate=22050, channels=1, seconds=.5)


class TestVoiceBridge(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        agent = Agent(MockBackend(), SessionStore(Path(self.temp.name)),
                      ROOT / "data/characters/eli.json")
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), create_handler(agent, "mock", voice=FakeVoice()))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def post(self, path, data):
        req = request.Request(self.url + path, json.dumps(data).encode(),
                              {"Content-Type": "application/json"}, method="POST")
        with request.urlopen(req, timeout=4) as response:
            return response.status, response.read(), response.headers.get("Content-Type")

    def test_status_and_health(self):
        with request.urlopen(self.url + "/api/voice/status", timeout=3) as reply:
            status = json.loads(reply.read())
        self.assertTrue(status["stt_ready"])
        with request.urlopen(self.url + "/api/health", timeout=3) as reply:
            health = json.loads(reply.read())
        self.assertTrue(health["voice_ready"])

    def test_recorded_words_are_only_returned_as_text(self):
        result, body, _ = self.post("/api/voice/transcribe", {
            "wav_b64": base64.b64encode(microphone_wav()).decode(),
            "sensitivity": 0.5})
        self.assertEqual(result, 200)
        self.assertEqual(json.loads(body)["transcript"], "Please check the door.")
        # No Agent.decide call, no session changes or world actions here.
        self.assertFalse(list(Path(self.temp.name).glob("*.json")))

    def test_eli_voice_is_raw_playable_wav(self):
        code, body, content_type = self.post("/api/voice/speak", {"text": "I'm listening."})
        self.assertEqual(code, 200)
        self.assertEqual(content_type, "audio/wav")
        self.assertTrue(body.startswith(b"RIFF"))

    def test_invalid_base64_rejected(self):
        with self.assertRaises(error.HTTPError) as error_context:
            self.post("/api/voice/transcribe", {"wav_b64": "%%%", "sensitivity": .5})
        self.assertEqual(error_context.exception.code, 400)

    def test_oversized_text_rejected_without_audio(self):
        with self.assertRaises(error.HTTPError) as error_context:
            self.post("/api/voice/speak", {"text": "bad"})
        self.assertEqual(error_context.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
