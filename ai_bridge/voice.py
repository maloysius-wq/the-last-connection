"""Local voice input/output for the Windows portable game.

Two separate, sandboxed subprocesses:
  whisper.cpp CLI: microphone WAV -> transcript only
  Piper CLI: Eli's confirmed spoken text -> WAV
Neither synthesizer nor recognizer talks to an outside service, and neither
has permission to infer or perform physical game actions.
"""
from __future__ import annotations

import audioop
import io
import struct
from pathlib import Path
import re
import subprocess
import tempfile
import time
import wave

from .nano import NanoVoice
from .native_nano import NativeNano


class VoiceError(ValueError):
    """User-facing local microphone/voice setup or input error."""


class VoiceUnavailable(VoiceError):
    """Optional voice assets aren't installed: typing is still fully usable."""


MAX_WAV_BYTES = 6_000_000
MAX_AUDIO_SECONDS = 16
MAX_TTS_CHARS = 500
MIN_AUDIO_SECONDS = 0.30


def normalize_wav(wav_data: bytes, sensitivity: float = 0.20) -> bytes:
    """Validate and resample recorded microphone PCM to 16-kHz mono WAV.

    The Godot microphone bus may operate at 44.1 or 48 kHz, possibly stereo;
    whisper-cli requires 16 kHz. Silences and garbage data do not become
    hallucinated commands. The WAV is never saved outside an ephemeral tempdir.
    """
    if not isinstance(wav_data, bytes) or not 44 <= len(wav_data) <= MAX_WAV_BYTES:
        raise VoiceError("Microphone recording is too large or empty.")
    if not isinstance(sensitivity, (int, float)) or not 0 <= sensitivity <= 1:
        raise VoiceError("Microphone sensitivity is invalid.")
    try:
        with wave.open(io.BytesIO(wav_data), "rb") as stream:
            sample_rate = stream.getframerate()
            channels = stream.getnchannels()
            width = stream.getsampwidth()
            count = stream.getnframes()
            compression = stream.getcomptype()
            if (compression != "NONE" or width != 2 or channels not in (1, 2) or
                    not 8000 <= sample_rate <= 192000 or count <= 0):
                raise VoiceError("Microphone requires uncompressed 16-bit PCM WAV.")
            duration = count / sample_rate
            if not MIN_AUDIO_SECONDS <= duration <= MAX_AUDIO_SECONDS:
                raise VoiceError("Hold V while speaking (between 0.3 and 16 seconds).")
            data = stream.readframes(count)
    except (EOFError, wave.Error, struct.error, OSError) as exc:
        raise VoiceError("The microphone recording is not a valid WAV file.") from exc
    if channels == 2:
        data = audioop.tomono(data, 2, 0.5, 0.5)
    # A small floor avoids whisper.cpp fabricating instructions from silent
    # rooms. Lower sensitivity means it takes a louder voice to trigger.
    min_rms = 120 + int((1.0 - float(sensitivity)) * 680)
    if audioop.rms(data, 2) < min_rms:
        raise VoiceError("I couldn't hear a clear voice. Check your mic or raise sensitivity.")
    if sample_rate != 16000:
        data, _ = audioop.ratecv(data, 2, 1, sample_rate, 16000, None)
    sink = io.BytesIO()
    with wave.open(sink, "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(16000)
        dst.writeframes(data)
    return sink.getvalue()


def clean_transcript(text: str) -> str:
    """Whisper output is player input, not permission until /api/decide."""
    if not isinstance(text, str):
        return ""
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\[\s*\d{2}:\d{2}:\d{2}\.\d+\s*-->\s*\d{2}:\d{2}:\d{2}\.\d+\s*\]\s*", "", line.strip()).strip()
        if not line or re.fullmatch(r"\[(?:BLANK_AUDIO|Music|Silence|Noise)\]", line, re.I):
            continue
        lines.append(line)
    joined = " ".join(lines).strip()
    if joined in ("[BLANK_AUDIO]", "[Music]", "(silence)"):
        return ""
    return joined[:600].strip()


class LocalVoiceService:
    """Runtime paths are always derived from the user's portable game folder."""

    def __init__(self, base: Path, runner=subprocess.run):
        self.base = Path(base)
        self.runner = runner
        self.nano = NanoVoice(self.base)
        self.native = NativeNano(self.base)
        self.last_engine = ""
        self.whisper = self.base / "runtime" / "voice" / "whisper" / "whisper-cli.exe"
        self.stt_model = self.base / "runtime" / "voice" / "whisper" / "ggml-tiny.en-q5_1.bin"
        self.piper = self.base / "runtime" / "voice" / "piper" / "piper.exe"
        self.tts_model = self.base / "runtime" / "voice" / "piper" / "en_US-joe-medium.onnx"
        self.tts_config = self.base / "runtime" / "voice" / "piper" / "en_US-joe-medium.onnx.json"

    def status(self) -> dict[str, object]:
        nano_ready = self.nano.installed() and not self.nano.failed
        piper_ready = self.piper.is_file() and self.tts_model.is_file() and self.tts_config.is_file()
        native_ready = self.native.installed()
        return {
            "stt_ready": self.whisper.is_file() and self.stt_model.is_file(),
            "tts_ready": nano_ready or piper_ready or native_ready,
            "native_ready": native_ready,
            "push_to_talk": "hold_v",
            "voice": "Chatterbox Nano" if nano_ready else "en_US-joe-medium",
            "nano_ready": nano_ready,
            "piper_ready": piper_ready,
            "offline": True,
            "profiles": self.profiles(),
            "cpu_threads": max(1, __import__("os").cpu_count() or 1),
            "last_metrics": self.native.last_metrics if self.last_engine == "native" else self.nano.last_metrics,
            "last_engine": self.last_engine,
        }

    def profiles(self):
        # No arbitrary paths from the HTTP endpoint. Custom WAVs stay local.
        result = [{"id": "default", "label": "Original Nano"},
                  {"id": "joe", "label": "Joe (male, synthetic reference)"}]
        if (self.nano.root / "eli-reference.wav").is_file():
            result.append({"id": "custom", "label": "Custom reference"})
        voices = self.nano.root / "voices"
        if voices.is_dir():
            for path in sorted(voices.glob("*.wav"))[:40]:
                if re.fullmatch(r"[A-Za-z0-9_-]{1,48}", path.stem) and not path.is_symlink():
                    result.append({"id": "ref:" + path.stem, "label": path.stem.replace("_", " ")})
        return result

    def _prepare_joe(self):
        root = self.nano.root
        path = root / "joe-reference.wav"
        if path.is_file():
            return
        if not all(p.is_file() for p in (self.piper, self.tts_model, self.tts_config)):
            raise VoiceUnavailable("The bundled Joe voice is unavailable.")
        root.mkdir(parents=True, exist_ok=True)
        # Reference is our own original text, rendered from the packaged CC0 Piper model.
        with tempfile.TemporaryDirectory(prefix="tlc-joe-", dir=self._temp_root()) as folder:
            output = Path(folder) / "joe.wav"
            result = self.runner([str(self.piper), "--model", str(self.tts_model),
                                  "--output_file", str(output)], cwd=str(self.piper.parent),
                                 input="The hallway is quiet now. I can hear something moving behind the wall. I need to figure out where I am, and whether there is another way out.\n",
                                 capture_output=True, text=True, timeout=30, encoding="utf-8",
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._check_run(result, "Joe reference")
            with wave.open(str(output), "rb") as w:
                if w.getnframes() / w.getframerate() <= 5:
                    raise VoiceError("Joe reference was too short.")
            output.replace(path)


    def warm(self):
        # Don't eagerly load two heavy voice engines.
        if not self.native.installed():
            self.nano.warm()

    def close(self):
        self.native.close()
        self.nano.close()

    def _reference(self, profile):
        if profile == "joe":
            self._prepare_joe()
            return self.nano.root / "joe-reference.wav"
        if profile == "custom" or (profile == "default" and (self.nano.root / "eli-reference.wav").is_file()):
            return self.nano.root / "eli-reference.wav"
        if profile.startswith("ref:"):
            return self.nano.root / "voices" / (profile[4:] + ".wav")
        return None

    def _temp_root(self) -> Path:
        temp = self.base / "temp"
        temp.mkdir(parents=True, exist_ok=True)
        return temp

    @staticmethod
    def _check_run(result: subprocess.CompletedProcess, task: str) -> None:
        if result.returncode != 0:
            detail = str(result.stderr or result.stdout or "")[-350:]
            raise VoiceError(f"{task} failed locally. {detail}")

    def transcribe(self, wav_data: bytes, sensitivity: float = 0.20) -> str:
        if not self.status()["stt_ready"]:
            raise VoiceUnavailable("Offline speech recognition isn't installed. You can still type to Eli.")
        prepared = normalize_wav(wav_data, sensitivity)
        with tempfile.TemporaryDirectory(prefix="tlc-stt-", dir=self._temp_root()) as folder:
            root = Path(folder)
            sample = root / "microphone.wav"
            result_base = root / "recognized"
            sample.write_bytes(prepared)
            args = [str(self.whisper), "-m", str(self.stt_model),
                    "-f", str(sample), "-l", "en", "-nt", "-np",
                    "-otxt", "-of", str(result_base)]
            try:
                result = self.runner(args, cwd=str(self.whisper.parent),
                                     capture_output=True, text=True, timeout=90,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise VoiceError("Local microphone transcription couldn't finish.") from exc
            self._check_run(result, "Speech recognition")
            recognized = result_base.with_suffix(".txt")
            # whisper.cpp's '-of' adds '.txt', not an arbitrary user path.
            text = (recognized.read_text(encoding="utf-8-sig", errors="replace")
                    if recognized.is_file() else "")
        transcript = clean_transcript(text)
        if not transcript:
            raise VoiceError("No clear words were recognized. Please try again or type.")
        return transcript

    def synthesize(self, spoken: str, emotion: str = "calm", *, profile="default", threads=0, engine="auto") -> bytes:
        if not self.status()["tts_ready"]:
            raise VoiceUnavailable("Eli's offline voice isn't installed; subtitles remain available.")
        if not isinstance(spoken, str) or not 1 <= len(spoken.strip()) <= MAX_TTS_CHARS:
            raise VoiceError("Speech text is empty or too long.")
        # Strip non-spoken role/format tokens, not words that Eli said.
        clean = re.sub(r"<[^>]{1,80}>", "", spoken).strip()
        if not clean:
            raise VoiceError("Nothing to speak.")
        if not isinstance(profile, str) or profile not in {p["id"] for p in self.profiles()}:
            raise VoiceError("Unknown local voice profile.")
        if type(threads) is not int or not 0 <= threads <= 32:
            raise VoiceError("Voice threads must be between 0 and 32.")
        if engine not in ("auto", "piper", "native"):
            raise VoiceError("Unknown local voice engine.")
        if engine == "native" and self.native.installed():
            try:
                self.nano._stop()
                reference = self._reference(profile)
                audio = self.native.synthesize(clean, emotion, reference=reference, threads=threads)
                self.last_engine = "native"
                return audio
            except (RuntimeError, ValueError, OSError, wave.Error, subprocess.TimeoutExpired):
                pass
        self.native._stop()
        if engine != "piper" and self.nano.installed() and not self.nano.failed:
            try:
                if profile == "joe":
                    self._prepare_joe()
                # Preserve existing API/tests for default calls.
                if profile == "default" and threads == 0:
                    audio = self.nano.synthesize(clean, emotion)
                else:
                    audio = self.nano.synthesize(clean, emotion, profile=profile, threads=threads)
                self.last_engine = "nano"
                return audio
            except (RuntimeError, ValueError, OSError, wave.Error, subprocess.TimeoutExpired):
                # Nano failures must not stop dialogue, subtitles or Piper.
                pass
        if not self.status()["piper_ready"]:
            raise VoiceUnavailable("Nano failed and Piper is unavailable; subtitles still work.")
        with tempfile.TemporaryDirectory(prefix="tlc-tts-", dir=self._temp_root()) as folder:
            output = Path(folder) / "eli.wav"
            command = [str(self.piper), "--model", str(self.tts_model),
                       "--output_file", str(output)]
            try:
                result = self.runner(command, cwd=str(self.piper.parent),
                                     input=clean + "\n", capture_output=True, text=True,
                                     timeout=90, encoding="utf-8",
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise VoiceError("Eli's local voice synthesis couldn't finish.") from exc
            self._check_run(result, "Voice synthesis")
            if not output.is_file() or not 44 <= output.stat().st_size <= 8_000_000:
                raise VoiceError("Eli's voice engine didn't produce playable audio.")
            audio = output.read_bytes()
            if not audio.startswith(b"RIFF") or audio[8:12] != b"WAVE":
                raise VoiceError("Eli's voice engine returned an invalid WAV.")
            self.last_engine = "piper"
            return audio
