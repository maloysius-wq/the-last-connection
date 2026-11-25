import io
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock
import wave

from ai_bridge.native_nano import NativeNano, native_config, validate_wav
from ai_bridge.voice import LocalVoiceService
from portable.launcher import find_gguf_candidates


def wav_bytes():
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\0\0" * 2400)
    return out.getvalue()


class NativeNanoTests(TestCase):
    def test_loopback_config_is_persistent_and_local(self):
        config = native_config(Path("voice.gguf"), 12345, 4)
        self.assertEqual(config["host"], "127.0.0.1")
        self.assertFalse(config["lazy_load"])
        self.assertFalse(config["log_request_body"])
        self.assertEqual(config["models"][0]["family"], "chatterbox_turbo")

    def test_wav_validation(self):
        audio = wav_bytes()
        self.assertAlmostEqual(validate_wav(audio), .1)
        with self.assertRaises(ValueError):
            validate_wav(audio[:-2])

    def test_install_marker_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            n = NativeNano(Path(tmp))
            binary = n.root / "runtime" / "audiocpp_server.exe"
            binary.parent.mkdir(parents=True)
            binary.touch()
            n.model.touch()
            self.assertFalse(n.installed())
            n.marker.touch()
            self.assertTrue(n.installed())

    def test_dialogue_model_scan_excludes_native_speech_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            voice = base / "models" / "chatterbox-nano-native"
            voice.mkdir(parents=True)
            (voice / "chatterbox-nano-q8_0.gguf").touch()
            dialogue = base / "models" / "eli.gguf"
            dialogue.touch()
            self.assertEqual(find_gguf_candidates(base), [dialogue.resolve()])

    def test_native_selection_and_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalVoiceService(Path(tmp))
            service.native.installed = Mock(return_value=True)
            service.native.synthesize = Mock(return_value=wav_bytes())
            service.nano.installed = Mock(return_value=True)
            service.nano.synthesize = Mock(return_value=wav_bytes())
            self.assertTrue(service.status()["native_ready"])
            self.assertEqual(service.synthesize("Hello", "angry", engine="native", threads=4), wav_bytes())
            service.native.synthesize.assert_called_once_with("Hello", "angry", reference=None, threads=4)
            self.assertEqual(service.last_engine, "native")
            service.nano.synthesize.assert_not_called()
            service.native.synthesize.side_effect = RuntimeError("native failed")
            self.assertEqual(service.synthesize("Hello", engine="native"), wav_bytes())
            self.assertEqual(service.last_engine, "nano")

    def test_native_imported_reference_resolves_local_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalVoiceService(Path(tmp))
            folder = service.nano.root / "voices"
            folder.mkdir(parents=True)
            ref = folder / "Eli.wav"
            ref.write_bytes(wav_bytes())
            service.native.installed = Mock(return_value=True)
            service.native.synthesize = Mock(return_value=wav_bytes())
            service.synthesize("Hello", engine="native", profile="ref:Eli")
            service.native.synthesize.assert_called_once_with("Hello", "calm", reference=ref, threads=0)
