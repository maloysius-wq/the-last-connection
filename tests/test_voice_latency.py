import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
import wave

from ai_bridge.voice import LocalVoiceService, VoiceError


class VoiceLatencyTests(TestCase):
    def test_custom_profile_and_threads_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalVoiceService(Path(tmp))
            folder = service.nano.root / "voices"
            folder.mkdir(parents=True)
            (folder / "Eli.wav").touch()
            service.nano.installed = Mock(return_value=True)
            service.nano.synthesize = Mock(return_value=b"wav")
            self.assertEqual(service.synthesize("Hello", "angry", profile="ref:Eli", threads=4), b"wav")
            service.nano.synthesize.assert_called_once_with("Hello", "angry", profile="ref:Eli", threads=4)

    def test_untrusted_paths_and_threads_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalVoiceService(Path(tmp))
            service.nano.installed = Mock(return_value=True)
            for options in ({"profile": "ref:../../x"}, {"threads": -1},
                            {"threads": True}, {"threads": 33}, {"engine": "unknown"}):
                with self.subTest(options=options), self.assertRaises(VoiceError):
                    service.synthesize("Hello", **options)

    def test_piper_mode_bypasses_nano(self):
        with tempfile.TemporaryDirectory() as tmp:
            def runner(args, **kwargs):
                with wave.open(args[-1], "wb") as out:
                    out.setnchannels(1)
                    out.setsampwidth(2)
                    out.setframerate(22050)
                    out.writeframes(b"\0\0" * 200)
                return Mock(returncode=0)
            service = LocalVoiceService(Path(tmp), runner=runner)
            for path in (service.piper, service.tts_model, service.tts_config):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            service.nano.installed = Mock(return_value=True)
            service.nano.synthesize = Mock()
            self.assertTrue(service.synthesize("Hello", engine="piper").startswith(b"RIFF"))
            service.nano.synthesize.assert_not_called()
