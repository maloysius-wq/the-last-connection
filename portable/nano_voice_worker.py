"""Separate optional Chatterbox Nano runtime, using pinned official weights."""
from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import time
import wave

REVISION = "71ccd1d0081b430592cea481f4307e764e07bc64"
FILES = ["t3_nano_v1.safetensors", "s3gen_meanflow.safetensors",
         "ve.safetensors", "conds.pt", "vocab.json", "merges.txt",
         "added_tokens.json", "special_tokens_map.json",
         "tokenizer_config.json", "README.md"]


def load(root):
    # Normal play must never trigger an implicit HF/model download.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    torch.set_num_threads(auto_threads())
    torch.set_num_interop_threads(1)
    model = ChatterboxTurboTTS.from_local(root / "checkpoint", device="cpu", nano=True)
    if model.conds is None:
        raise RuntimeError("Nano's built-in voice is missing")
    return model


def auto_threads():
    # Torch's default can oversubscribe older CPUs. Leave one logical core
    # available for UI and the GGUF server, with a sensible upper bound.
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def voice_conditionals(model, root, profile, cache):
    import re
    if profile == "default":
        # Preserve previous installations that explicitly installed a custom voice.
        path = root / "eli-reference.wav"
        if not path.is_file():
            model.conds = cache["builtin"]
            return
    elif profile == "custom":
        path = root / "eli-reference.wav"
    elif profile == "joe":
        path = root / "joe-reference.wav"
    elif isinstance(profile, str) and re.fullmatch(r"ref:[A-Za-z0-9_-]{1,48}", profile):
        path = root / "voices" / (profile[4:] + ".wav")
    else:
        raise ValueError("Unknown voice profile")
    if not path.is_file() or path.is_symlink():
        raise ValueError("Voice reference missing")
    key = (str(path), path.stat().st_mtime_ns)
    if key not in cache:
        # Limit cached reference conditionals to avoid growing RAM indefinitely.
        if len(cache) >= 5:
            cache.pop(next(k for k in cache if k != "builtin"))
        model.prepare_conditionals(str(path))
        cache[key] = model.conds
    else:
        model.conds = cache[key]


def render(model, text):
    import torch
    with torch.inference_mode():
        audio = model.generate(text)
    samples = audio.detach().cpu().reshape(-1).clamp(-1, 1)
    if not samples.numel() or not bool(torch.isfinite(samples).all()):
        raise RuntimeError("Nano produced invalid audio")
    pcm = (samples * 32767).to(torch.int16).numpy().tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(model.sr))
        w.writeframes(pcm)
    return out.getvalue()


def install(root):
    # Only the separately invoked setup script can use the network.
    from huggingface_hub import snapshot_download
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "ready.json"
    marker.unlink(missing_ok=True)
    snapshot_download(repo_id="ResembleAI/chatterbox-nano",
                      revision=REVISION, allow_patterns=FILES,
                      local_dir=str(root / "checkpoint"))
    start = time.monotonic()
    model = load(root)
    audio = render(model, "[fear] Is someone there?")
    with wave.open(io.BytesIO(audio), "rb") as w:
        seconds = w.getnframes() / w.getframerate()
        if seconds < 0.2:
            raise RuntimeError("Nano smoke generated no usable speech")
    (root / "sample.wav").write_bytes(audio)
    marker.write_text(json.dumps({"revision": REVISION, "cpu": True,
                                  "smoke_seconds": round(time.monotonic() - start, 2),
                                  "audio_seconds": round(seconds, 2)}), encoding="utf-8")
    print("Nano ready. Listen to models/chatterbox-nano/sample.wav.")


def serve(root):
    # stdout is the protocol; all library logging goes to the local log.
    output = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        load_started = time.monotonic()
        model = load(root)
        cache = {"builtin": model.conds}
        import torch
        print("Nano load seconds:", round(time.monotonic() - load_started, 2),
              file=sys.stderr, flush=True)
        for line in sys.stdin:
            started = time.monotonic()
            try:
                data = json.loads(line)
                text = data.get("text")
                if not isinstance(text, str) or not 1 <= len(text) <= 520:
                    raise ValueError("Invalid speech text")
                threads = data.get("threads", 0)
                if type(threads) is not int or not 0 <= threads <= 32:
                    raise ValueError("Invalid thread count")
                threads = min(threads or auto_threads(), os.cpu_count() or 1)
                if torch.get_num_threads() != threads:
                    torch.set_num_threads(threads)
                voice_conditionals(model, root, data.get("profile", "default"), cache)
                synth_started = time.monotonic()
                wav = render(model, text)
                seconds = round(time.monotonic() - synth_started, 3)
                with wave.open(io.BytesIO(wav), "rb") as stream:
                    duration = round(stream.getnframes() / stream.getframerate(), 3)
                response = {"wav": base64.b64encode(wav).decode("ascii"),
                            "seconds": seconds, "audio_seconds": duration, "threads": threads}
                print("Nano synthesis seconds:", seconds,
                      "total:", round(time.monotonic() - started, 2),
                      "audio seconds:", duration, "threads:", threads,
                      file=sys.stderr, flush=True)
            except Exception as exc:
                print("Nano synthesis error:", repr(exc), file=sys.stderr, flush=True)
                response = {"error": "Local synthesis failed"}
            output.write("TLC_NANO " + json.dumps(response) + "\n")
            output.flush()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--setup", action="store_true")
    a = p.parse_args()
    if a.setup:
        install(a.root)
    else:
        serve(a.root)
