import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
import queue
import json
import base64
import io
import wave
from ai_bridge.nano import NanoVoice
from ai_bridge.voice import LocalVoiceService
from portable.nano_voice_worker import check_cuda


class CudaTests(TestCase):
    def test_separate_environment_and_marker_shared_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            cpu = NanoVoice(Path(tmp))
            cuda = NanoVoice(Path(tmp), device="cuda")
            self.assertEqual(cpu.root, cuda.root)
            self.assertNotEqual(cpu.python, cuda.python)
            self.assertNotEqual(cpu.marker, cuda.marker)
            cuda.python.parent.mkdir(parents=True)
            cuda.python.touch()
            cuda.script.touch()
            (cuda.root / "checkpoint").mkdir()
            for name in ("t3_nano_v1.safetensors", "s3gen_meanflow.safetensors", "ve.safetensors", "conds.pt"):
                (cuda.root / "checkpoint" / name).touch()
            cpu.marker.touch()
            self.assertFalse(cuda.installed())
            cuda.marker.touch()
            self.assertTrue(cuda.installed())

    def test_cuda_no_device_and_low_memory_refused(self):
        torch = Mock()
        torch.cuda.is_available.return_value = False
        with self.assertRaisesRegex(RuntimeError, "CUDA unavailable"):
            check_cuda(torch)
        torch.cuda.is_available.return_value = True
        torch.cuda.get_device_capability.return_value = (6, 1)
        torch.cuda.get_arch_list.return_value = ["sm_60", "sm_75"]
        torch.cuda.mem_get_info.return_value = (1024**3, 6*1024**3)
        torch.cuda.get_device_name.return_value = "GTX 1060"
        torch.__version__ = "2.6.0+cu124"
        torch.version.cuda = "12.4"
        with self.assertRaisesRegex(RuntimeError, "3 GiB"):
            check_cuda(torch)
        torch.cuda.get_arch_list.return_value = ["sm_75"]
        with self.assertRaisesRegex(RuntimeError, "does not target"):
            check_cuda(torch)

    def test_cuda_selection_and_direct_cpu_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalVoiceService(Path(tmp))
            service.nano_cuda.installed = Mock(return_value=True)
            service.nano_cuda.synthesize = Mock(return_value=b"gpu")
            service.nano.installed = Mock(return_value=True)
            service.nano.synthesize = Mock(return_value=b"cpu")
            service.native.synthesize = Mock()
            service.native_vulkan.synthesize = Mock()
            self.assertTrue(service.status()["nano_cuda_ready"])
            self.assertEqual(service.synthesize("Hello", "afraid", engine="nano_cuda"), b"gpu")
            service.nano_cuda.synthesize.assert_called_once_with("Hello", "afraid", profile="default", threads=0)
            self.assertEqual(service.last_engine, "nano_cuda")
            service.nano_cuda.synthesize.side_effect = RuntimeError("CUDA OOM")
            self.assertEqual(service.synthesize("Hello", engine="nano_cuda"), b"cpu")
            self.assertEqual(service.last_engine, "nano")
            service.native.synthesize.assert_not_called()
            service.native_vulkan.synthesize.assert_not_called()

    def test_cuda_cold_load_and_synthesis_have_separate_deadlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            cuda = NanoVoice(Path(tmp), device="cuda")
            proc = Mock()
            cuda._proc = proc
            cuda._start = Mock()
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(b"\0\0" * 100)
            reply = json.dumps({"device": "cuda", "wav": base64.b64encode(buf.getvalue()).decode()})
            cuda._responses = Mock()
            cuda._responses.get.side_effect = [json.dumps({"ready": True, "device": "cuda"}), reply, reply]
            cuda.synthesize("Warmup", optional_warmup=True)
            cuda.synthesize("Real reply")
            self.assertEqual([c.kwargs["timeout"] for c in cuda._responses.get.call_args_list],
                             [120, 75, 75])
            self.assertFalse(cuda.failed)

    def test_startup_timeout_logs_stage_and_remains_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cuda = NanoVoice(Path(tmp), device="cuda")
            cuda._proc = Mock()
            cuda._start = Mock()
            cuda._stop = Mock()
            cuda._responses = Mock()
            cuda._responses.get.side_effect = queue.Empty
            with self.assertRaisesRegex(RuntimeError, "worker startup timed out"):
                cuda.synthesize("Warmup", optional_warmup=True)
            self.assertFalse(cuda.failed)
            self.assertIn("worker startup timed out", (Path(tmp) / "logs" / cuda.log_name).read_text())
            with self.assertRaisesRegex(RuntimeError, "worker startup timed out"):
                cuda.synthesize("Real reply")
            self.assertTrue(cuda.failed)

    def test_failed_warmup_never_loads_cpu_and_real_reply_retries_cuda(self):
        from ai_bridge.voice import VoiceUnavailable
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalVoiceService(Path(tmp))
            service.nano_cuda.installed = Mock(return_value=True)
            service.nano.installed = Mock(return_value=True)
            service.nano.synthesize = Mock(return_value=b"cpu")
            service.nano_cuda.synthesize = Mock(side_effect=[RuntimeError("timeout"), b"gpu"])
            with self.assertRaises(VoiceUnavailable):
                service.synthesize("Warmup", engine="nano_cuda", warmup_only=True)
            self.assertFalse(service.nano_cuda.failed)
            service.nano.synthesize.assert_not_called()
            self.assertEqual(service.synthesize("Real reply", engine="nano_cuda"), b"gpu")
            self.assertEqual(service.last_engine, "nano_cuda")
            self.assertEqual(service.nano_cuda.synthesize.call_count, 2)
