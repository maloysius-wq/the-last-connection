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
    torch.set_num_threads(max(1, min(8, (os.cpu_count() or 2) // 2)))
    torch.set_num_interop_threads(1)
    model = ChatterboxTurboTTS.from_local(root / "checkpoint", device="cpu", nano=True)
    ref = root / "eli-reference.wav"
    if ref.is_file():
        model.prepare_conditionals(str(ref))
    elif model.conds is None:
        raise RuntimeError("Nano's built-in voice is missing")
    return model


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
        model = load(root)
        for line in sys.stdin:
            started = time.monotonic()
            try:
                data = json.loads(line)
                text = data.get("text")
                if not isinstance(text, str) or not 1 <= len(text) <= 520:
                    raise ValueError("Invalid speech text")
                wav = render(model, text)
                response = {"wav": base64.b64encode(wav).decode("ascii")}
                print("Nano synthesis seconds:", round(time.monotonic() - started, 2),
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
