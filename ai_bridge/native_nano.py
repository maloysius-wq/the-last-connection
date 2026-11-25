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

def native_config(model, port, threads):
    return {"host": "127.0.0.1", "port": port, "backend": "cpu",
            "threads": threads, "lazy_load": False, "max_loaded_models": 1,
            "log_request_body": False,
            "models": [{"id": "eli", "family": "chatterbox_turbo",
                        "path": str(model), "task": "tts", "mode": "offline"}]}

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
    def __init__(self, base, *, popen=subprocess.Popen, timeout=60):
        self.base = Path(base).resolve()
        self.root = self.base / "models" / "chatterbox-nano-native"
        self.model = self.root / MODEL_NAME
        self.marker = self.root / "ready.json"
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
        files = list((self.root / "runtime").rglob("audiocpp_server.exe"))
        return files[0] if len(files) == 1 else None

    def installed(self):
        return (not self.failed and self.marker.is_file() and self.model.is_file()
                and self.executable() is not None)

    def _log(self, message):
        logs = self.base / "logs"
        logs.mkdir(exist_ok=True)
        with (logs / "nano-native.log").open("a", encoding="utf-8") as log:
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
        config = self.root / "server.json"
        config.write_text(json.dumps(native_config(self.model, port, threads)), encoding="utf-8")
        logs = self.base / "logs"
        logs.mkdir(exist_ok=True)
        started = time.monotonic()
        with (logs / "nano-native.log").open("a", encoding="utf-8") as log:
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
                self.last_metrics = {"engine": "native", "queue_seconds": round(started-queued,3),
                                     "bridge_seconds": round(time.monotonic()-started,3),
                                     "synthesis_seconds": round(time.monotonic()-generation,3),
                                     "audio_seconds": round(duration,3), "threads": threads}
                self._log(self.last_metrics)
                return data
            except (OSError, RuntimeError, ValueError, wave.Error, EOFError) as exc:
                self.failed = True
                self._stop()
                self._log(f"Native Nano failed: {type(exc).__name__}: {exc}")
                raise RuntimeError("Native Nano failed locally") from exc
