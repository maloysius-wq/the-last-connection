"""Nano adapter tests do not require Torch or network/model assets."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import wave

from ai_bridge.nano import directed_text, NanoVoice
from ai_bridge.voice import LocalVoiceService


class NanoVoiceTests(unittest.TestCase):
    def test_supported_emotion_tags_and_plain_neutral(self):
        self.assertEqual(directed_text("Who are you?", "afraid"), "[fear] Who are you?")
        self.assertEqual(directed_text("Stop.", "angry"), "[angry] Stop.")
        self.assertEqual(directed_text("Finally.", "relieved"), "[sigh] Finally.")
        self.assertEqual(directed_text("Hello.", "calm"), "Hello.")
        self.assertEqual(directed_text("[laugh] Stop.", "angry"), "[angry] Stop.")
        self.assertEqual(directed_text("Hello.", {"unexpected": True}), "Hello.")

    def test_missing_setup_keeps_piper_available(self):
        with tempfile.TemporaryDirectory() as temp:
            voice = LocalVoiceService(Path(temp))
            self.assertFalse(voice.nano.installed())
            self.assertFalse(voice.status()["nano_ready"])
            self.assertFalse(voice.status()["tts_ready"])
            for path in (voice.piper, voice.tts_model, voice.tts_config):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            self.assertTrue(voice.status()["tts_ready"])
            self.assertEqual(voice.status()["voice"], "en_US-joe-medium")

    def test_installed_nano_preferred_and_emotion_forwarded(self):
        with tempfile.TemporaryDirectory() as temp:
            voice = LocalVoiceService(Path(temp))
            voice.nano.installed = Mock(return_value=True)
            voice.nano.synthesize = Mock(return_value=b"local audio")
            self.assertEqual(voice.status()["voice"], "Chatterbox Nano")
            self.assertEqual(voice.synthesize("No.", "angry"), b"local audio")
            voice.nano.synthesize.assert_called_once_with("No.", "angry")

    def test_failure_falls_back_to_piper_without_losing_text(self):
        with tempfile.TemporaryDirectory() as temp:
            def fake(args, **kwargs):
                out = Path(args[-1])
                with wave.open(str(out), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(22050)
                    w.writeframes(b"\0\0" * 100)
                self.assertEqual(kwargs["input"], "No.\n")
                return Mock(returncode=0)
            voice = LocalVoiceService(Path(temp), runner=fake)
            for path in (voice.piper, voice.tts_model, voice.tts_config):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            voice.nano.installed = Mock(return_value=True)
            voice.nano.synthesize = Mock(side_effect=RuntimeError("failed"))
            self.assertTrue(voice.synthesize("No.", "angry").startswith(b"RIFF"))

    def test_worker_requires_explicit_setup_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            nano = NanoVoice(Path(temp), popen=Mock())
            self.assertFalse(nano.installed())
            nano.warm()
            nano._popen.assert_not_called()
            nano.close()


if __name__ == "__main__":
    unittest.main()
