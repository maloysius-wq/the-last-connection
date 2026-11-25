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


MIN_CUDA_FREE_BYTES = 3 * 1024**3


def check_cuda(torch):
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable: check NVIDIA driver and CUDA-enabled torch")
    torch.cuda.set_device(0)
    major, minor = torch.cuda.get_device_capability(0)
    arches = torch.cuda.get_arch_list()
    free, total = torch.cuda.mem_get_info(0)
    info = {"device": torch.cuda.get_device_name(0), "capability": [major, minor],
            "architectures": arches, "free_bytes": free, "total_bytes": total,
            "torch": torch.__version__, "cuda": torch.version.cuda}
    print("Nano CUDA admission:", json.dumps(info), file=sys.stderr, flush=True)
    # CUDA cubins are compatible with equal/newer minor revisions of the same
    # major architecture (e.g. sm_60 on sm_61). Actual kernels must also pass.
    if not any(a.startswith("sm_") and a[3:].isdigit() and
               int(a[3:]) // 10 == major and int(a[3:]) % 10 <= minor for a in arches):
        raise RuntimeError("Installed PyTorch CUDA binary does not target this GPU")
    if free < MIN_CUDA_FREE_BYTES:
        raise RuntimeError("Less than 3 GiB free VRAM; close GPU apps or reduce dialogue GPU offload")
    # Test actual FP32 kernel execution, not just driver enumeration.
    x = torch.ones((32, 32), device="cuda", dtype=torch.float32)
    if float((x @ x)[0, 0].item()) != 32.0:
        raise RuntimeError("CUDA kernel self-test failed")
    torch.cuda.synchronize()
    del x
    return info


def cuda_metrics(torch):
    free, total = torch.cuda.mem_get_info(0)
    return {"free_bytes": free, "total_bytes": total,
            "allocated_bytes": torch.cuda.memory_allocated(0),
            "reserved_bytes": torch.cuda.memory_reserved(0),
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(0),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(0)}


def load(root, device="cpu"):
    # Normal play must never trigger an implicit HF/model download.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    torch.set_num_threads(auto_threads())
    torch.set_num_interop_threads(1)
    if device == "cuda":
        check_cuda(torch)
        torch.cuda.reset_peak_memory_stats(0)
    # GTX 1060 lacks Tensor Cores; retain official FP32 inference rather than
    # introducing mixed precision or unsupported attention kernels.
    model = ChatterboxTurboTTS.from_local(root / "checkpoint", device=device, nano=True)
    if device == "cuda":
        torch.cuda.synchronize()
        print("Nano CUDA loaded:", json.dumps(cuda_metrics(torch)), file=sys.stderr, flush=True)
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


def install_cuda(root):
    # Reuse the already-installed official checkpoint; no snapshot download.
    marker = root / "ready-cuda.json"
    marker.unlink(missing_ok=True)
    if not all((root / "checkpoint" / name).is_file() for name in FILES if name != "README.md"):
        raise RuntimeError("Install original CPU Nano first; CUDA reuses its checkpoint")
    import torch
    started = time.monotonic()
    model = load(root, "cuda")
    startup = time.monotonic() - started
    timings = []
    for name, prompt in (("sample-cuda.wav", "[fear] Is someone there?"),
                         ("sample-cuda-warm.wav", "[angry] Who are you?")):
        print("Testing CUDA speech:", prompt, flush=True)
        start = time.monotonic()
        audio = render(model, prompt)
        torch.cuda.synchronize()
        with wave.open(io.BytesIO(audio), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
        if duration < .2:
            raise RuntimeError("CUDA Nano produced no usable speech")
        (root / name).write_bytes(audio)
        timing = {"seconds": round(time.monotonic()-start,3), "audio_seconds": round(duration,3),
                  **cuda_metrics(torch)}
        print(json.dumps(timing), flush=True)
        timings.append(timing)
    summary = {"revision": REVISION, "device": "cuda", "torch": torch.__version__,
               "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0),
               "capability": list(torch.cuda.get_device_capability(0)),
               "startup_seconds": round(startup,3), "samples": timings}
    marker.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("CUDA Nano ready. Two real speech samples passed.", flush=True)


def check_cuda_build():
    import torch
    import torchaudio
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    if torch.version.cuda != "12.4" or not torch.__version__.startswith("2.6.0") or not torchaudio.__version__.startswith("2.6.0"):
        raise RuntimeError("Incorrect CUDA dependency build")
    print("CUDA 12.4 torch and torchaudio imports passed:", torch.__version__, torchaudio.__version__)
    if not torch.cuda.is_available():
        print("No GPU exposed; build check only, no speech activation.")
    else:
        check_cuda(torch)


def serve(root, device="cpu", ready_protocol=False):
    # stdout is the protocol; all library logging goes to the local log.
    output = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        load_started = time.monotonic()
        model = load(root, device)
        cache = {"builtin": model.conds}
        import torch
        print("Nano load seconds:", round(time.monotonic() - load_started, 2),
              file=sys.stderr, flush=True)
        if ready_protocol:
            output.write("TLC_NANO " + json.dumps({"ready": True, "device": device}) + "\n")
            output.flush()
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
                            "seconds": seconds, "audio_seconds": duration, "threads": threads,
                            "device": device}
                if device == "cuda":
                    response["gpu_memory"] = cuda_metrics(torch)
                    print("Nano CUDA memory:", json.dumps(response["gpu_memory"]), file=sys.stderr, flush=True)
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
    p.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    p.add_argument("--check-cuda-build", action="store_true")
    p.add_argument("--ready-protocol", action="store_true")
    a = p.parse_args()
    if a.check_cuda_build:
        check_cuda_build()
    elif a.setup and a.device == "cuda":
        install_cuda(a.root)
    elif a.setup:
        install(a.root)
    else:
        serve(a.root, a.device, a.ready_protocol)
