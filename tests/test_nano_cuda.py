import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
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
