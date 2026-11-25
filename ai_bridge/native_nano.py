"""Optional native Chatterbox Nano Q8 server, owned by the game launcher."""
from __future__ import annotations
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from urllib import request, error
import wave
from .nano import directed_text

MAX_WAV = 8_000_000
MODEL_NAME = "chatterbox-nano-q8_0.gguf"

# Conservative admission guard, not a claim about peak model memory.
MIN_VULKAN_FREE_BYTES = 2 * 1024**3


def select_vulkan_device(report, index=None):
    if not isinstance(report, dict) or not isinstance(report.get("devices"), list):
        raise RuntimeError("Vulkan device probe returned invalid data")
    candidates = []
    for dev in report["devices"]:
        if (not isinstance(dev, dict) or dev.get("backend") != "vulkan"
                or dev.get("type") != "gpu" or type(dev.get("index")) is not int):
            continue
        if index is not None and dev["index"] != index:
            continue
        mem = dev.get("memory")
        if not isinstance(mem, dict):
            continue
        free, total = mem.get("free_bytes"), mem.get("total_bytes")
        if type(free) is int and type(total) is int and MIN_VULKAN_FREE_BYTES <= free <= total:
            candidates.append(dev)
    if not candidates:
        raise RuntimeError("No eligible discrete Vulkan GPU with at least 2 GiB reported free; use original Nano or reduce dialogue GPU memory")
    return max(candidates, key=lambda d: d["memory"]["free_bytes"])


def native_config(model, port, threads, backend="cpu", device=None):
    if backend not in ("cpu", "vulkan"):
        raise ValueError("Unknown native backend")
    config = {"host": "127.0.0.1", "port": port, "backend": backend,
            "threads": threads, "lazy_load": False, "max_loaded_models": 1,
            "log_request_body": False,
            "models": [{"id": "eli", "family": "chatterbox_turbo",
                        "path": str(model), "task": "tts", "mode": "offline"}]}
    if backend == "vulkan":
        if type(device) is not int or device < 0:
            raise ValueError("A verified Vulkan device is required")
        config["device"] = device
    return config

def validate_wav(data):
    if not 44 <= len(data) <= MAX_WAV:
        raise ValueError("Native Nano audio size")
    with wave.open(io.BytesIO(data), "rb") as stream:
        count, rate = stream.getnframes(), stream.getframerate()
        if (stream.getnchannels() != 1 or stream.getsampwidth() != 2
                or not 8000 <= rate <= 48000 or not count
                or len(stream.readframes(count)) != count * 2):
            raise ValueError("Native Nano requires complete mono PCM16 WAV")
        return count / rate

class NativeNano:
    def __init__(self, base, *, backend="cpu", popen=subprocess.Popen, runner=subprocess.run, timeout=60):
        if backend not in ("cpu", "vulkan"):
            raise ValueError("Unknown native backend")
        self.backend = backend
        self.engine = "native_vulkan" if backend == "vulkan" else "native"
        self._runner = runner
        self.base = Path(base).resolve()
        self.root = self.base / "models" / "chatterbox-nano-native"
        self.model = self.root / MODEL_NAME
        self.marker = self.root / ("ready-vulkan.json" if backend == "vulkan" else "ready.json")
        self.runtime = self.root / ("runtime-vulkan" if backend == "vulkan" else "runtime")
        self.log_name = "nano-native-vulkan.log" if backend == "vulkan" else "nano-native.log"
        self.device_info = {}
        self._popen = popen
        self.timeout = timeout
        self._lock = threading.Lock()
        self._proc = None
        self._threads = self._port = None
        self._closing = False
        self.failed = False
        self.last_metrics = {}
        self._http = request.build_opener(request.ProxyHandler({}))

    def executable(self):
        files = list(self.runtime.rglob("audiocpp_server.exe"))
        return files[0] if len(files) == 1 else None

    def installed(self):
        return (not self.failed and self.marker.is_file() and self.model.is_file()
                and self.executable() is not None)

    def _probe_device(self, exe, index=None):
        result = self._runner([str(exe), "--list-devices", "--json"], cwd=str(exe.parent),
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            raise RuntimeError("Vulkan device enumeration failed")
        report = json.loads(result.stdout)
        return select_vulkan_device(report, index)

    def _log(self, message):
        logs = self.base / "logs"
        logs.mkdir(exist_ok=True)
        with (logs / self.log_name).open("a", encoding="utf-8") as log:
            log.write(str(message) + "\n")

    def _stop(self):
        proc, self._proc = self._proc, None
        self._threads = self._port = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)

    def close(self):
        self._closing = True
        self._stop()

    def _start(self, threads):
        if self._closing or not self.installed():
            raise RuntimeError("Native Nano not ready")
        if self._proc is not None and self._proc.poll() is None and self._threads == threads:
            return
        self._stop()
        exe = self.executable()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        device = None
        if self.backend == "vulkan":
            # The dialogue model is already running by now. Probe live free
            # VRAM, not the idle figure from installation. Never select CPU.
            ready = json.loads(self.marker.read_text(encoding="utf-8-sig"))
            device = ready.get("device")
            if type(device) is not int or device < 0:
                raise RuntimeError("Rerun Vulkan setup to verify your device")
            self.device_info = self._probe_device(exe, device)
            self._log({"before_start": self.device_info})
        config = self.root / ("server-vulkan.json" if self.backend == "vulkan" else "server.json")
        config.write_text(json.dumps(native_config(self.model, port, threads, self.backend, device)), encoding="utf-8")
        logs = self.base / "logs"
        logs.mkdir(exist_ok=True)
        started = time.monotonic()
        with (logs / self.log_name).open("a", encoding="utf-8") as log:
            self._proc = self._popen([str(exe), "--config", str(config), "--no-ui"],
                                    cwd=str(exe.parent), stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._threads, self._port = threads, port
        deadline = time.monotonic() + min(30, self.timeout)
        while time.monotonic() < deadline:
            if self._closing or self._proc is None or self._proc.poll() is not None:
                raise RuntimeError("Native Nano server stopped")
            try:
                with self._http.open(f"http://127.0.0.1:{port}/health", timeout=1) as resp:
                    if resp.status == 200:
                        self._log(f"Native server startup seconds: {time.monotonic()-started:.3f}; threads: {threads}")
                        return
            except (OSError, error.URLError):
                time.sleep(.15)
        raise RuntimeError("Native Nano server startup timed out")

    def synthesize(self, text, emotion="calm", *, reference=None, threads=0):
        threads = min(threads or max(1, min(8, (os.cpu_count() or 2)//2)), os.cpu_count() or 1)
        queued = time.monotonic()
        with self._lock:
            started = time.monotonic()
            try:
                self._start(threads)
                body = {"model": "eli", "input": directed_text(text, emotion),
                        "response_format": "wav"}
                if reference is not None:
                    path = Path(reference)
                    if not path.is_file() or path.is_symlink():
                        raise ValueError("Native reference is missing")
                    body["voice_ref"] = {"type": "path", "path": str(path.resolve())}
                req = request.Request(f"http://127.0.0.1:{self._port}/v1/audio/speech",
                                      data=json.dumps(body).encode("utf-8"),
                                      headers={"Content-Type": "application/json"}, method="POST")
                generation = time.monotonic()
                with self._http.open(req, timeout=self.timeout) as resp:
                    if resp.headers.get_content_type() != "audio/wav":
                        raise ValueError("Native Nano response is not WAV")
                    data = resp.read(MAX_WAV + 1)
                duration = validate_wav(data)
                self.last_metrics = {"engine": self.engine, "queue_seconds": round(started-queued,3),
                                     "bridge_seconds": round(time.monotonic()-started,3),
                                     "synthesis_seconds": round(time.monotonic()-generation,3),
                                     "audio_seconds": round(duration,3), "threads": threads}
                self._log(self.last_metrics)
                return data
            except (OSError, RuntimeError, ValueError, wave.Error, EOFError, subprocess.TimeoutExpired) as exc:
                self.failed = True
                exit_code = self._proc.poll() if self._proc is not None else None
                self._stop()
                self._log(f"Native Nano ({self.backend}) failed: {type(exc).__name__}: {exc}; process exit: {exit_code}")
                raise RuntimeError("Native Nano failed locally") from exc
