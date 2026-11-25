"""Optional CPU-only Chatterbox Nano subprocess; no model downloads in play."""
from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import wave
import time

# These are actual tokens in the pinned Nano tokenizer, not Turbo's ignored
# exaggeration/CFG controls. Use at most one style marker per spoken segment.
EMOTION_TAG = {
    "afraid": "[fear]", "anxious": "[fear]", "overwhelmed": "[fear]",
    "angry": "[angry]", "frustrated": "[angry]",
    "suspicious": "[whispering]", "relieved": "[sigh]",
    "hopeful": "[happy]", "warm": "[happy]",
}
PREFIX = "TLC_NANO "
MAX_AUDIO = 8_000_000


def directed_text(text: str, emotion: str) -> str:
    # Strip arbitrary bracket directives before inserting our own token.
    clean = re.sub(r"\[[^\]\r\n]{1,80}\]", "", text).strip()
    if not clean:
        raise ValueError("Nothing to speak.")
    tag = EMOTION_TAG.get(emotion, "") if isinstance(emotion, str) else ""
    return (tag + " " if tag else "") + clean


class NanoVoice:
    def __init__(self, base: Path, *, popen=subprocess.Popen, timeout=75):
        self.base = Path(base).resolve()
        self.root = self.base / "models" / "chatterbox-nano"
        self.python = self.root / "venv" / "Scripts" / "python.exe"
        self.script = self.base / "nano_voice_worker.py"
        self.marker = self.root / "ready.json"
        self._popen = popen
        self.timeout = timeout
        self._proc = None
        self._responses = queue.Queue()
        self._lock = threading.Lock()
        self._closing = False
        self.failed = False
        self.last_metrics = {}

    def installed(self):
        return (self.python.is_file() and self.script.is_file()
                and self.marker.is_file()
                and all((self.root / "checkpoint" / name).is_file()
                        for name in ("t3_nano_v1.safetensors",
                                     "s3gen_meanflow.safetensors",
                                     "ve.safetensors", "conds.pt")))

    def _read(self, proc, responses):
        try:
            for line in proc.stdout:
                if line.startswith(PREFIX):
                    responses.put(line[len(PREFIX):])
        finally:
            responses.put(None)

    def _start(self):
        if self._closing or self.failed or not self.installed():
            raise RuntimeError("Nano is not ready")
        if self._proc is not None and self._proc.poll() is None:
            return
        env = os.environ.copy()
        env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                    "HF_HOME": str(self.root / "hf-cache"),
                    "TEMP": str(self.base / "temp"),
                    "TMP": str(self.base / "temp"),
                    "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"})
        (self.base / "logs").mkdir(exist_ok=True)
        (self.base / "temp").mkdir(exist_ok=True)
        self._responses = queue.Queue()
        with (self.base / "logs" / "nano-voice.log").open("a", encoding="utf-8") as log:
            proc = self._popen(
                [str(self.python), "-u", str(self.script), "--root", str(self.root)],
                cwd=str(self.base), env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._proc = proc
        threading.Thread(target=self._read, args=(proc, self._responses),
                         daemon=True).start()

    def warm(self):
        """Start loading once, without blocking the launcher or downloading."""
        if self.installed() and not self.failed:
            with self._lock:
                try:
                    self._start()
                except (OSError, RuntimeError):
                    self.failed = True

    def _stop(self):
        proc = self._proc
        self._proc = None
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
            for stream in (proc.stdin, proc.stdout):
                if stream is not None:
                    stream.close()

    def close(self):
        # Don't wait for a long synthesis on game shutdown.
        self._closing = True
        self._stop()

    def synthesize(self, text: str, emotion: str = "calm", *, profile="default", threads=0) -> bytes:
        prompt = directed_text(text, emotion)
        queued = time.monotonic()
        with self._lock:
            try:
                started = time.monotonic()
                self._start()
                proc = self._proc
                proc.stdin.write(json.dumps({"text": prompt, "profile": profile,
                                             "threads": threads}, ensure_ascii=False) + "\n")
                proc.stdin.flush()
                response = self._responses.get(timeout=self.timeout)
                if response is None:
                    raise RuntimeError("Nano worker exited")
                result = json.loads(response)
                if not isinstance(result, dict) or not result.get("wav"):
                    raise RuntimeError("Nano synthesis failed")
                encoded = result["wav"]
                if not isinstance(encoded, str) or len(encoded) > 11_000_000:
                    raise ValueError("Nano audio too large")
                audio = base64.b64decode(encoded, validate=True)
                if not 44 <= len(audio) <= MAX_AUDIO:
                    raise ValueError("Nano audio size")
                with wave.open(io.BytesIO(audio), "rb") as w:
                    if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getnframes() <= 0:
                        raise ValueError("Nano requires mono PCM16 WAV")
                self.last_metrics = {"queue_seconds": round(started - queued, 3),
                                     "bridge_seconds": round(time.monotonic() - started, 3),
                                     "synthesis_seconds": result.get("seconds"),
                                     "audio_seconds": result.get("audio_seconds"),
                                     "threads": result.get("threads"),
                                     "profile": profile}
                return audio
            except (OSError, RuntimeError, ValueError, TypeError, queue.Empty,
                    EOFError, wave.Error, AttributeError) as exc:
                self.failed = True
                self._stop()
                raise RuntimeError("Nano failed locally; Piper fallback selected") from exc
