"""Portable, offline-first GGUF setup and Windows backend orchestration.

Network access is used *only* when the player explicitly chooses to download
model weights on first launch, never for AI inference. Downloads stay beside
this application, on the user's selected drive.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Callable
from urllib import request

MODEL_FILENAME = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
MODEL_URL = (
    "https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/"
    "resolve/main/" + MODEL_FILENAME + "?download=true"
)
# Download bytes are not bundled. Qwen original weights are Apache-2.0;
# quantization is by bartowski (model card linked in portable README).
MIN_MODEL_SIZE = 100_000_000
MAX_MODEL_SIZE = 7_000_000_000
Progress = Callable[[int, int | None], None]


class RuntimeSetupError(RuntimeError):
    pass


def is_gguf(path: Path) -> bool:
    try:
        if path.suffix.lower() != ".gguf" or not path.is_file():
            return False
        with path.open("rb") as handle:
            return handle.read(4) == b"GGUF"
    except OSError:
        return False


def download_default_model(base: Path, progress: Progress | None = None,
                           opener=None) -> Path:
    """Download exactly one reviewed quantization, resuming a .part when safe.

    The model never goes into Windows profile caches. Interrupted downloads
    remain a .part file for next launch; they are never mistaken for a model.
    """
    opener = opener or request.urlopen
    directory = base / "models"
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / MODEL_FILENAME
    partial = directory / (MODEL_FILENAME + ".part")
    if is_gguf(final) and final.stat().st_size >= MIN_MODEL_SIZE:
        return final.resolve()
    if final.exists():
        raise RuntimeSetupError(f"Existing model appears invalid: {final}")
    disk = shutil.disk_usage(directory)
    # A Q4_K_M is ~2.5 GB. Permit resume while ensuring 1GB spare.
    downloaded = partial.stat().st_size if partial.is_file() else 0
    if disk.free + downloaded < 3_300_000_000:
        raise RuntimeSetupError("Not enough free space on the game drive for the model download (about 3.3 GB recommended).")
    if downloaded > MAX_MODEL_SIZE:
        partial.unlink()
        downloaded = 0
    headers = {"User-Agent": "TheLastConnection/Prototype", "Accept-Encoding": "identity"}
    if downloaded:
        headers["Range"] = f"bytes={downloaded}-"
    req = request.Request(MODEL_URL, headers=headers)
    try:
        with opener(req, timeout=90) as response:
            # HTTP redirects on approved Hugging Face CDN must remain HTTPS.
            actual_url = response.geturl() if hasattr(response, "geturl") else MODEL_URL
            if not actual_url.startswith("https://"):
                raise RuntimeSetupError("The model download redirected to an insecure address.")
            code = response.status if hasattr(response, "status") else response.getcode()
            if code not in (200, 206):
                raise RuntimeSetupError(f"Model server returned HTTP {code}")
            if code == 206 and not downloaded:
                raise RuntimeSetupError("Unexpected partial model response")
            if code == 206:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {downloaded}-"):
                    raise RuntimeSetupError("Model download resume range did not match the local file")
            else:
                downloaded = 0
            length = int(response.headers.get("Content-Length", "0") or 0)
            expected = downloaded + length if length else None
            if expected is not None and (expected < MIN_MODEL_SIZE or expected > MAX_MODEL_SIZE):
                raise RuntimeSetupError("Model download has an unexpected size")
            total = downloaded
            mode = "ab" if code == 206 else "wb"
            with partial.open(mode) as handle:
                if progress:
                    progress(total, expected)
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_MODEL_SIZE:
                        raise RuntimeSetupError("Model exceeds the allowed download size")
                    handle.write(chunk)
                    if progress:
                        progress(total, expected)
            if (expected is not None and total != expected) or total < MIN_MODEL_SIZE:
                raise RuntimeSetupError("Model download was incomplete; restart the game to resume")
            with partial.open("rb") as handle:
                if handle.read(4) != b"GGUF":
                    raise RuntimeSetupError("Downloaded data is not a GGUF model")
            partial.replace(final)
            return final.resolve()
    except OSError as exc:
        raise RuntimeSetupError(f"Unable to download model: {exc}") from exc


def runtime_candidates(base: Path, acceleration: str = "auto") -> list[tuple[str, Path, int]]:
    """Vulkan for broad NVIDIA/AMD/Intel support; always keep CPU fallback."""
    if acceleration not in ("auto", "vulkan", "cpu"):
        raise RuntimeSetupError("acceleration must be auto, vulkan, or cpu")
    runtime = base / "runtime" / "llama"
    cpu = runtime / "cpu" / "llama-server.exe"
    vulkan = runtime / "vulkan" / "llama-server.exe"
    legacy_cpu = runtime / "llama-server.exe"
    if not cpu.is_file() and legacy_cpu.is_file():
        cpu = legacy_cpu
    choices = []
    if acceleration != "cpu" and vulkan.is_file():
        choices.extend((name, vulkan, layers) for name, layers in
                       (("vulkan", 99), ("vulkan-partial", 16)))
    if cpu.is_file():
        choices.append(("cpu", cpu, 0))
    if not choices:
        raise RuntimeSetupError("Model runner missing. Re-extract the complete Windows portable ZIP.")
    return choices


def start_model_server(base: Path, model: Path, config: dict, log_handle,
                       ready: Callable[[str], bool], progress: Callable[[str], None] | None = None,
                       popen=subprocess.Popen, sleep=time.sleep, startup_timeout: float = 150,
                       env: dict[str, str] | None = None):
    """Try GPU offload, partial GPU offload, then CPU. Return (process, mode).

    Never mask a failure with pretend success; only server /health = ok counts.
    """
    mode = config.get("acceleration", "auto")
    attempts = []
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for name, exe, layers in runtime_candidates(base, mode):
        if progress:
            progress("Starting " + name + " inference...")
        cmd = [str(exe), "--model", str(model), "--host", "127.0.0.1",
               "--port", "8877", "--alias", "tlc-eli", "--ctx-size", "4096",
               "--jinja", "--n-gpu-layers", str(layers)]
        log_handle.write(f"\n[The Last Connection] Attempting {name}, GPU layers={layers}\n")
        log_handle.flush()
        try:
            proc = popen(cmd, cwd=str(exe.parent), stdout=log_handle,
                         stderr=subprocess.STDOUT, env=env or os.environ.copy(),
                         creationflags=flags)
        except OSError as exc:
            attempts.append(f"{name}: {exc}")
            continue
        count = max(1, int(startup_timeout / 0.5))
        succeeded = False
        for _ in range(count):
            if proc.poll() is not None:
                attempts.append(f"{name}: exited with code {proc.returncode}")
                break
            if ready("http://127.0.0.1:8877/health"):
                succeeded = True
                break
            sleep(0.5)
        if succeeded:
            return proc, name, attempts
        if proc.poll() is None:
            attempts.append(f"{name}: startup timeout")
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    raise RuntimeSetupError("Unable to start local AI on GPU or CPU. Check logs/llama-server.log. " + "; ".join(attempts))
