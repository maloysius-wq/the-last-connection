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
    tkinter.Label(window, text="Loading your local model from D:. No download required.",
                  font=("Segoe UI", 9)).pack(pady=(0, 12))
    window.update()
    return window


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
    llama = base / "runtime" / "llama" / "llama-server.exe"
    for path in (game, llama):
        if not path.is_file():
            raise PortableSetupError(f"Portable runtime is incomplete: missing {path.name}. Download the complete Windows ZIP.")
    model = select_model(base, config, chooser=choose_model_dialog)
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
        server_proc = subprocess.Popen([
            str(llama), "--model", str(model), "--host", "127.0.0.1",
            "--port", "8877", "--alias", "tlc-eli", "--ctx-size", "4096", "--jinja",
            "--n-gpu-layers", "0",
        ], cwd=str(llama.parent), stdout=model_log, stderr=subprocess.STDOUT,
           env=env, creationflags=windows_flags)
        # Model initialization can take time on slow, CPU-only PCs.
        for _ in range(600):
            if server_proc.poll() is not None:
                raise PortableSetupError("Local model server stopped unexpectedly. See logs/llama-server.log on D:.")
            if _ready("http://127.0.0.1:8877/health"):
                break
            if splash:
                splash.update()
            time.sleep(1)
        else:
            raise PortableSetupError("Local AI model did not finish loading. See logs/llama-server.log.")

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
    except (OSError, ValueError, PortableSetupError) as exc:
        notify(f"Unable to start the portable game:\n\n{exc}", error=True)
        sys.exit(1)
