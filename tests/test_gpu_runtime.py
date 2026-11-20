"""Backend selection, CPU fallback and explicit first-launch download tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from io import BytesIO, StringIO
import unittest

from portable import runtime


class FakeResponse:
    def __init__(self, data, status=200, headers=None):
        self.stream = BytesIO(data)
        self.status = status
        self.headers = headers or {"Content-Length": str(len(data))}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return "https://cdn-lfs.huggingface.co/sample"
    def read(self, count):
        return self.stream.read(count)


class FakeProc:
    def __init__(self):
        self.returncode = None
        self.terminated = False
    def poll(self):
        return self.returncode
    def terminate(self):
        self.terminated = True
        self.returncode = 1
    def wait(self, timeout=None):
        return self.returncode
    def kill(self):
        self.returncode = -9


class TestGpuRuntime(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        for backend in ("cpu", "vulkan"):
            path = self.base / "runtime" / "llama" / backend / "llama-server.exe"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"MZ")
        self.model = self.base / "models" / "original.gguf"
        self.model.parent.mkdir(parents=True)
        self.model.write_bytes(b"GGUFdummy")

    def tearDown(self):
        self.temp.cleanup()

    def test_prefer_vulkan_with_cpu_fallback(self):
        names = [item[0] for item in runtime.runtime_candidates(self.base)]
        self.assertEqual(names, ["vulkan", "vulkan-partial", "cpu"])
        self.assertEqual([x[2] for x in runtime.runtime_candidates(self.base)], [99, 16, 0])

    def test_cpu_mode_only(self):
        self.assertEqual([x[0] for x in runtime.runtime_candidates(self.base, "cpu")], ["cpu"])

    def test_missing_vulkan_still_runs_cpu(self):
        (self.base / "runtime/llama/vulkan/llama-server.exe").unlink()
        self.assertEqual([x[0] for x in runtime.runtime_candidates(self.base)], ["cpu"])

    def test_invalid_backend_rejected(self):
        with self.assertRaises(runtime.RuntimeSetupError):
            runtime.runtime_candidates(self.base, "cloud")

    def test_gpu_success_uses_offload(self):
        calls = []
        def popen(cmd, **kw):
            calls.append(cmd)
            return FakeProc()
        proc, name, failures = runtime.start_model_server(
            self.base, self.model, {}, StringIO(),
            ready=lambda _: True, popen=popen, sleep=lambda _: None)
        self.assertEqual(name, "vulkan")
        self.assertEqual(calls[0][-1], "99")
        self.assertEqual(failures, [])
        self.assertIsInstance(proc, FakeProc)

    def test_gpu_failure_falls_back_to_cpu(self):
        calls = []
        def popen(cmd, **kw):
            calls.append(cmd)
            proc = FakeProc()
            if len(calls) < 3:
                proc.returncode = 1
            return proc
        proc, name, failures = runtime.start_model_server(
            self.base, self.model, {}, StringIO(),
            ready=lambda _: True, popen=popen, sleep=lambda _: None)
        self.assertEqual(name, "cpu")
        self.assertEqual([x[-1] for x in calls], ["99", "16", "0"])
        self.assertEqual(len(failures), 2)
        self.assertIsInstance(proc, FakeProc)

    def test_download_is_not_automatic_and_targets_game_folder(self):
        # The downloader is callable only after explicit chooser confirmation.
        body = b"GGUF" + b"q" * 100
        with patch.object(runtime, "MIN_MODEL_SIZE", 16), patch.object(
            runtime, "shutil") as fs:
            fs.disk_usage.return_value.free = 10_000_000_000
            result = runtime.download_default_model(self.base,
                opener=lambda req, timeout: FakeResponse(body))
        self.assertEqual(result, (self.base / "models" / runtime.MODEL_FILENAME).resolve())
        self.assertEqual(result.read_bytes(), body)
        self.assertFalse(list(self.base.rglob("*.part")))

    def test_download_resume_range(self):
        partial = self.base / "models" / (runtime.MODEL_FILENAME + ".part")
        partial.write_bytes(b"GGUF" + b"q" * 20)
        remaining = b"r" * 40
        captured = []
        def opener(req, timeout):
            captured.append(req.get_header("Range"))
            return FakeResponse(remaining, 206, {"Content-Length": str(len(remaining)),
                                                "Content-Range": "bytes 24-63/64"})
        with patch.object(runtime, "MIN_MODEL_SIZE", 16), patch.object(
            runtime, "shutil") as fs:
            fs.disk_usage.return_value.free = 10_000_000_000
            result = runtime.download_default_model(self.base, opener=opener)
        self.assertEqual(captured, ["bytes=24-"])
        self.assertEqual(result.stat().st_size, 64)

    def test_bad_model_magic_does_not_replace_existing_model(self):
        with patch.object(runtime, "MIN_MODEL_SIZE", 16), patch.object(
            runtime, "shutil") as fs:
            fs.disk_usage.return_value.free = 10_000_000_000
            with self.assertRaises(runtime.RuntimeSetupError):
                runtime.download_default_model(self.base,
                    opener=lambda req, timeout: FakeResponse(b"HTML" + b"x" * 100))
        self.assertFalse((self.base / "models" / runtime.MODEL_FILENAME).exists())


if __name__ == "__main__":
    unittest.main()
