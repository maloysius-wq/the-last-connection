"""Manual Windows smoke using downloaded native assets; not unit test discovery."""
import sys
from pathlib import Path
import wave
import io

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_bridge.native_nano import NativeNano, validate_wav

native = NativeNano(Path("portable"))
assert native.installed()
try:
    first = native.synthesize("Who are you?", "angry", threads=4)
    process = native._proc
    (native.root / "adapter-first.wav").write_bytes(first)
    print("first", native.last_metrics)
    warm = native.synthesize("I can hear you.", "calm", threads=4)
    assert native._proc is process
    (native.root / "adapter-warm.wav").write_bytes(warm)
    print("warm", native.last_metrics)
    # Use a generated, local synthetic voice as the reference; no external person.
    ref = native.root / "adapter-reference.wav"
    # Reuse the two actual synthetic utterances to make a >5s PCM reference.
    # Avoid generating a long extra clip only to verify the reference path.
    with wave.open(io.BytesIO(first), "rb") as a, wave.open(io.BytesIO(warm), "rb") as b:
        assert a.getframerate() == b.getframerate()
        frames = a.readframes(a.getnframes()) + b.readframes(b.getnframes())
        with wave.open(str(ref), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(a.getframerate())
            out.writeframes(frames * 3)
    assert validate_wav(ref.read_bytes()) > 5
    cloned = native.synthesize("I am here.", "relieved", reference=ref, threads=4)
    assert native._proc is process
    (native.root / "adapter-clone.wav").write_bytes(cloned)
    print("clone", native.last_metrics)
finally:
    native.close()
assert process.poll() is not None
