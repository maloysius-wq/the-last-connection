"""Start an all-in-one Windows build without Ollama, system Python or Godot editor.

Build this as a PyInstaller onedir app. All runtime files stay beside the
executable on the selected drive. No system-wide services are installed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib import request, error

from ai_bridge.agent import Agent, LlamaCppBackend, SessionStore
from ai_bridge.server import create_handler
from portable.runtime import (RuntimeSetupError, download_default_model, runtime_candidates,
                              start_model_server, MODEL_FILENAME)
from http.server import ThreadingHTTPServer


class PortableSetupError(RuntimeError):
    pass


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def find_gguf_candidates(base: Path, extra_roots: tuple[Path, ...] = ()) -> list[Path]:
    """Reuse files in-place; do not silently select an ambiguous/different model."""
    roots = (base / "models", *extra_roots)
    matches: list[Path] = []
    for root in roots:
        if root.is_dir():
            try:
                matches.extend(p.resolve() for p in root.rglob("*.gguf") if p.is_file())
            except (OSError, PermissionError):
                continue
    return sorted(set(matches))


def select_model(base: Path, config: dict, candidates: list[Path] | None = None,
                 chooser=None) -> Path:
    """Never download or duplicate model weights. Ask the user if ambiguous."""
    model_value = config.get("model_path", "")
    if model_value:
        model = Path(os.path.expandvars(str(model_value))).expanduser()
        if model.is_file() and model.suffix.lower() == ".gguf":
            return model.resolve()
        raise PortableSetupError(f"Configured GGUF model was not found: {model}")
    if candidates is None:
        candidates = find_gguf_candidates(base, (Path("D:/LocalForge"),))
    if len(candidates) == 1:
        return candidates[0]
    if chooser is None:
        raise PortableSetupError("Choose an existing .gguf model; no valid model_path is configured.")
    picked = chooser()
    if picked:
        model = Path(picked)
        if model.is_file() and model.suffix.lower() == ".gguf":
            return model.resolve()
    raise PortableSetupError("No GGUF model was selected.")


def choose_model_dialog() -> str:
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    try:
        return filedialog.askopenfilename(
            parent=root, title="Select Eli's local GGUF AI model",
            initialdir=r"D:\LocalForge" if Path("D:/LocalForge").exists() else str(app_directory()),
            filetypes=[("GGUF AI model", "*.gguf")],
        )
    finally:
        root.destroy()


def notify(text: str, title: str = "The Last Connection", error: bool = False) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)
    else:
        print(f"{title}: {text}", file=sys.stderr if error else sys.stdout)


def _ready(url: str) -> bool:
    try:
        with request.urlopen(url, timeout=1) as response:
            return response.status == 200 and json.loads(response.read(1000)).get("status") == "ok"
    except (OSError, ValueError, error.URLError):
        return False


def _available_port(port: int) -> bool:
    import socket
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def make_loading_window():
    """Small visible indication while the local CPU model initializes."""
    if sys.platform != "win32":
        return None
    import tkinter
    window = tkinter.Tk()
    window.title("The Last Connection")
    window.geometry("420x135")
    window.resizable(False, False)
    tkinter.Label(window, text="Establishing connection with Eli...", font=("Segoe UI", 12, "bold")).pack(pady=(20, 5))
    tkinter.Label(window, text="Loading your model locally. No cloud inference.",
                  font=("Segoe UI", 9)).pack(pady=(0, 12))
    window.update()
    return window


def download_with_progress(base: Path) -> Path:
    """One-time download after the player explicitly approves the ~2.5GB file."""
    import tkinter
    root = tkinter.Tk()
    root.title("Installing Eli's AI model")
    root.geometry("460x140")
    root.resizable(False, False)
    label = tkinter.Label(root, text="Downloading Qwen3 4B Q4_K_M into this game folder...", wraplength=440)
    label.pack(pady=(24, 12))
    detail = tkinter.Label(root, text="Stored under models/ beside the game, not in C: AppData.")
    detail.pack()
    last_update = [0.0]

    def show_progress(done: int, expected: int | None) -> None:
        now = time.monotonic()
        if now - last_update[0] < 0.15 and (not expected or done < expected):
            return
        last_update[0] = now
        mb = done / 1_000_000
        label.config(text=(f"Downloading Eli's model: {mb:.0f} MB"
                           + (f" / {expected / 1_000_000:.0f} MB" if expected else "")))
        root.update()
    try:
        root.update()
        return download_default_model(base, progress=show_progress)
    finally:
        root.destroy()


def choose_or_install_model(base: Path, config: dict,
                            chooser=choose_model_dialog,
                            downloader=download_with_progress,
                            ask=None) -> Path:
    """Existing model or explicit user-approved model download, no LocalForge dependency."""
    saved = config.get("model_path", "")
    if saved:
        try:
            return select_model(base, config)
        except PortableSetupError:
            # A copied game may have an old drive letter/model path.
            config.pop("model_path", None)
    candidates = find_gguf_candidates(base, (Path("D:/LocalForge"),))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return select_model(base, {}, candidates=candidates, chooser=chooser)
    if ask is None:
        if sys.platform != "win32":
            raise PortableSetupError("Choose a local GGUF model to start.")
        import ctypes
        ask = lambda: ctypes.windll.user32.MessageBoxW(
            None, "No GGUF model was found.\n\nYES: Download the default Qwen3 4B (~2.5 GB) into the game's models folder. Internet is needed ONCE.\n\nNO: Choose an existing GGUF file on this computer.\n\nCANCEL: Exit without downloading.",
            "The Last Connection | First-time model setup", 0x23)
    selection = ask()
    if selection == 6:
        return downloader(base)
    if selection == 7:
        return select_model(base, {}, candidates=[], chooser=chooser)
    raise PortableSetupError("Model setup cancelled. Nothing was downloaded.")


def main() -> int:
    base = app_directory()
    saves = base / "user_data"
    logs = base / "logs"
    saves.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    config_path = base / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    if not isinstance(config, dict):
        raise PortableSetupError("config.json must contain a JSON object")
    game = base / "TheLastConnectionGame.exe"
    if not game.is_file():
        raise PortableSetupError("TheLastConnectionGame.exe is missing. Re-extract the complete portable ZIP.")
    # Resolve available GPU and CPU runtime binaries before loading a model.
    runtime_candidates(base, config.get("acceleration", "auto"))
    model = choose_or_install_model(base, config)
    if config.get("model_path") != str(model):
        config["model_path"] = str(model)
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    if not _available_port(8877) or not _available_port(8765):
        raise PortableSetupError("Another program is using a required local port (8877 or 8765). Close the other process and retry.")

    # This is intentionally a single-use owner: all children stop when game closes.
    windows_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    model_log = (logs / "llama-server.log").open("a", encoding="utf-8")
    env = os.environ.copy()
    env["TEMP"] = str(base / "temp")
    env["TMP"] = str(base / "temp")
    (base / "temp").mkdir(exist_ok=True)
    server_proc = None
    bridge = None
    bridge_thread = None
    splash = None
    try:
        splash = make_loading_window()
        def loading_notice(message: str) -> None:
            if splash:
                splash.title("The Last Connection | " + message)
                splash.update()

        server_proc, acceleration, failed_attempts = start_model_server(
            base, model, config, model_log, _ready, progress=loading_notice, env=env,
        )
        (logs / "runtime-status.json").write_text(json.dumps({
            "acceleration": acceleration,
            "gpu_active": acceleration.startswith("vulkan"),
            "failed_attempts": failed_attempts,
        }, indent=2), encoding="utf-8")

        if splash:
            splash.destroy()
            splash = None
        agent = Agent(LlamaCppBackend(), SessionStore(saves / "sessions"),
                      resource_directory() / "data" / "characters" / "eli.json")
        bridge = ThreadingHTTPServer(("127.0.0.1", 8765), create_handler(agent, "llama.cpp"))
        bridge_thread = threading.Thread(target=bridge.serve_forever, daemon=True)
        bridge_thread.start()
        with (logs / "game.log").open("a", encoding="utf-8") as game_log:
            child = subprocess.Popen([str(game)], cwd=str(base), env=env, stdout=game_log,
                                     stderr=subprocess.STDOUT)
            return child.wait()
    finally:
        if splash:
            splash.destroy()
        if bridge:
            bridge.shutdown()
            bridge.server_close()
        if bridge_thread:
            bridge_thread.join(timeout=5)
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server_proc.kill()
        model_log.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, PortableSetupError, RuntimeSetupError) as exc:
        notify(f"Unable to start the portable game:\n\n{exc}", error=True)
        sys.exit(1)
