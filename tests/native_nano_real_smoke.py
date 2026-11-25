"""Manual Windows smoke using downloaded native assets; not unit test discovery."""
import sys
from pathlib import Path
import wave

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
    clip = native.synthesize("The hallway is quiet now. I can hear something moving behind the wall. I need to figure out where I am and whether there is another way out.", threads=4)
    assert validate_wav(clip) > 5
    ref.write_bytes(clip)
    cloned = native.synthesize("I am still here.", "relieved", reference=ref, threads=4)
    assert native._proc is process
    (native.root / "adapter-clone.wav").write_bytes(cloned)
    print("clone", native.last_metrics)
finally:
    native.close()
assert process.poll() is not None
