"""Start an all-in-one Windows build without Ollama, system Python or Godot editor.

Build this as a PyInstaller onedir app. All runtime files stay beside the
executable on the selected drive. No system-wide services are installed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib import request, error

from ai_bridge.agent import Agent, LlamaCppBackend, SessionStore
from ai_bridge.server import create_handler
from ai_bridge.voice import LocalVoiceService, VoiceError, VoiceUnavailable
from portable.runtime import (RuntimeSetupError, download_default_model, runtime_candidates,
                              start_model_server, MODEL_FILENAME)
from portable.update_service import UpdateService, TAG_RE
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
                matches.extend(p.resolve() for p in root.rglob("*.gguf")
                               if p.is_file() and not any(
                                   part.lower().startswith("chatterbox-nano") for part in p.relative_to(root).parts))
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


def warm_dialogue(messages=None) -> dict:
    """Exercise actual local token generation, never a player/session turn."""
    started = time.monotonic()
    payload = {"model": "tlc-eli", "messages": [
        {"role": "user", "content": "Reply with one word: ready."}],
        "max_tokens": 2, "temperature": 0, "stream": False, "cache_prompt": False}
    if messages:
        # Prime the actual production static prefix instead of a tiny unrelated
        # greeting. A discarded token never enters player conversation history.
        payload.update(messages=messages, cache_prompt=True, n_cache_reuse=64)
    req = request.Request("http://127.0.0.1:8877/v1/chat/completions",
                          json.dumps(payload).encode("utf-8"),
                          {"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=60 if messages else 20) as response:
            reply = json.loads(response.read(64_000))
        if not reply.get("choices") or int(reply.get("usage", {}).get("completion_tokens", 0)) < 1:
            raise ValueError("No generated token confirmed")
        state = {"status": "ready"}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        # Optional preflight: never invent success or block normal play forever.
        state = {"status": "failed", "reason": type(exc).__name__}
    state["seconds"] = round(time.monotonic() - started, 3)
    return state


def read_voice_settings(path: Path) -> dict:
    """Read only scalar [voice] settings from Godot's ConfigFile, never rewrite saves."""
    settings = {"engine": "auto", "profile": "default", "threads": 0,
                "muted": False, "text_only": False}
    if not path.is_file():
        return settings
    section = ""
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if re.fullmatch(r"\[[A-Za-z0-9_]+\]", line):
            section = line[1:-1]
        elif section == "voice" and "=" in line:
            key, value = (part.strip() for part in line.split("=", 1))
            if key not in settings:
                continue
            try:
                parsed = json.loads(value)
            except ValueError:
                continue
            if type(parsed) is type(settings[key]):
                settings[key] = parsed
    settings["threads"] = max(0, min(32, settings["threads"]))
    return settings


def warm_selected_voice(service, settings: dict) -> dict:
    """Exercise the saved persistent voice in the same service used by the bridge."""
    started = time.monotonic()
    engine = settings["engine"]
    options = {key: settings[key] for key in ("engine", "profile", "threads")}
    report = {"settings": options, "status": "skipped", "engine": engine}
    try:
        if settings["muted"] or settings["text_only"]:
            report["reason"] = "speech disabled by saved preference"
        else:
            available = service.status()
            if engine == "piper" or (engine == "auto" and not available["nano_ready"]
                                      and available["piper_ready"]):
                # Piper and Whisper are per-request CLI processes, not persistent
                # models: no retained inference state to warm before launch.
                if not available["piper_ready"]:
                    raise VoiceUnavailable("Piper is not installed.")
                report.update(status="not_required", engine="piper")
            elif engine == "auto" and not available["nano_ready"] and not available["tts_ready"]:
                report["reason"] = "optional voice not installed"
            else:
                service.synthesize("I'm listening.", "calm", warmup_only=True, **options)
                expected = "nano" if engine == "auto" else engine
                if service.last_engine != expected:
                    raise VoiceUnavailable("Selected voice did not report readiness.")
                report.update(status="ready", engine=expected)
    except (VoiceError, VoiceUnavailable, OSError, RuntimeError, ValueError) as exc:
        report.update(status="failed", reason=str(exc)[:300])
    report["seconds"] = round(time.monotonic() - started, 3)
    return report


def choose_startup_voice_failure(report: dict, splash) -> str:
    """No hidden fallback or in-game cold start after a failed preflight."""
    if sys.platform != "win32":
        return "quit"
    from tkinter import messagebox
    choice = messagebox.askyesnocancel(
        "Eli's voice did not initialize",
        str(report.get("reason", "See voice log.")) +
        "\n\nYes: retry before entering the game.\n"
        "No: enter with speech disabled for this launch.\n"
        "Cancel: close the game.",
        parent=splash)
    return "retry" if choice is True else "without_speech" if choice is False else "quit"


def run_startup_voice(service, settings, progress, splash=None, choose=choose_startup_voice_failure):
    """Wait for the bounded worker to finish, keeping the loading window responsive."""
    while True:
        result = {}
        def run():
            result.update(warm_selected_voice(service, settings))
        worker = threading.Thread(target=run, daemon=True)
        started = time.monotonic()
        worker.start()
        while worker.is_alive():
            progress("Initializing Eli's voice (" + str(int(time.monotonic() - started)) + "s)")
            worker.join(timeout=0.1)
        report = result or {"status": "failed", "reason": "Voice warmup did not return."}
        if report["status"] != "failed":
            return report
        choice = choose(report, splash)
        if choice == "retry":
            continue
        if choice == "without_speech":
            return dict(report, status="disabled")
        return dict(report, status="cancelled")


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
    window.geometry("470x155")
    window.resizable(False, False)
    tkinter.Label(window, text="Establishing connection with Eli...", font=("Segoe UI", 12, "bold")).pack(pady=(20, 5))
    window.stage_label = tkinter.Label(window, text="Loading local AI...", font=("Segoe UI", 10), wraplength=440)
    window.stage_label.pack(pady=(0, 6))
    tkinter.Label(window, text="The game opens after initialization. No cloud inference.",
                  font=("Segoe UI", 9)).pack(pady=(0, 12))
    window.protocol("WM_DELETE_WINDOW", lambda: None)
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


def start_update_helper(base: Path, tag: str) -> None:
    """Run independent updater outside the install folder before launcher exits."""
    if not TAG_RE.fullmatch(tag):
        raise PortableSetupError("Invalid update identifier. Check for updates again.")
    updater = base / "TheLastConnectionUpdater.exe"
    if not updater.is_file():
        raise PortableSetupError("Updater executable is missing. Re-extract the complete portable ZIP.")
    helper_dir = base.parent / ".TheLastConnection-updater"
    helper_dir.mkdir(parents=True, exist_ok=True)
    helper = helper_dir / "TheLastConnectionUpdater.exe"
    shutil.copy2(updater, helper)
    # PyInstaller onefile must unpack outside the folder we're about to swap.
    temp = base.parent / ".TheLastConnection-update-temp"
    temp.mkdir(parents=True, exist_ok=True)
    helper_env = os.environ.copy()
    helper_env["TEMP"] = str(temp)
    helper_env["TMP"] = str(temp)
    subprocess.Popen([
        str(helper), "--base", str(base), "--tag", tag,
        "--parent-pid", str(os.getpid()),
    ], cwd=str(base.parent), env=helper_env,
       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))



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
    voice_service = None
    splash = None
    game_exit_code = 0
    pending_update = base / "updates" / "request.json"
    # Do not act on stale requests from a prior interrupted session.
    if pending_update.exists():
        pending_update.unlink()
    try:
        splash = make_loading_window()
        def loading_notice(message: str) -> None:
            if splash:
                splash.title("The Last Connection | " + message)
                splash.stage_label.config(text=message)
                splash.update()

        # Voice warmup runs after the dialogue model is resident, using the
        # player's saved engine/profile from Godot rather than guessing here.
        voice_service = LocalVoiceService(base)
        server_proc, acceleration, failed_attempts = start_model_server(
            base, model, config, model_log, _ready, progress=loading_notice, env=env,
        )
        # llama.cpp's own load-time warmup does not necessarily exercise
        # the chat endpoint. Generate a tiny discarded completion first.
        loading_notice("Warming up dialogue and prompt cache...")
        backend = LlamaCppBackend(compact=True, streaming=config.get("stream_dialogue", True) is not False,
                                  cache_reuse=64 if config.get("reuse_prompt_chunks", True) is not False else 0)
        agent = Agent(backend, SessionStore(saves / "sessions"),
                      resource_directory() / "data" / "characters" / "eli.json")
        dialogue_warmup = {"status": "skipped"}
        if config.get("dialogue_warmup", True) is not False:
            warm_result = {}
            def run_warmup():
                messages = agent._messages({}, "Reply with one word: ready.",
                                           goal=True, world={"objects": {}})
                warm_result.update(warm_dialogue(backend.prepare_goal_messages(messages)))
            worker = threading.Thread(target=run_warmup, daemon=True)
            worker.start()
            while worker.is_alive():
                if splash:
                    splash.update()
                worker.join(timeout=0.05)
            dialogue_warmup = warm_result or {"status": "failed"}
        model_log.write("\n[The Last Connection] Dialogue warmup: " + json.dumps(dialogue_warmup) + "\n")
        model_log.flush()
        if server_proc.poll() is not None:
            raise PortableSetupError("Dialogue server exited during startup. See logs/llama-server.log.")
        voice_settings = read_voice_settings(saves / "tlc_save.cfg")
        voice_report = run_startup_voice(voice_service, voice_settings, loading_notice, splash)
        voice_service.startup_report = voice_report
        model_log.write("\n[The Last Connection] Voice startup: " + json.dumps(voice_report) + "\n")
        model_log.flush()
        (logs / "runtime-status.json").write_text(json.dumps({
            "dialogue_warmup": dialogue_warmup,
            "voice_warmup": voice_report,
            "acceleration": acceleration,
            "gpu_active": acceleration.startswith("vulkan"),
            "failed_attempts": failed_attempts,
        }, indent=2), encoding="utf-8")

        if voice_report["status"] == "cancelled":
            return 1
        if server_proc.poll() is not None:
            raise PortableSetupError("Dialogue server exited during voice initialization. See logs/llama-server.log.")
        loading_notice("Opening the game...")
        if splash:
            splash.destroy()
            splash = None
        bridge = ThreadingHTTPServer(("127.0.0.1", 8765),
                                     create_handler(agent, "llama.cpp", updater=UpdateService(base),
                                                    voice=voice_service))
        bridge_thread = threading.Thread(target=bridge.serve_forever, daemon=True)
        bridge_thread.start()
        with (logs / "game.log").open("a", encoding="utf-8") as game_log:
            child = subprocess.Popen([str(game)], cwd=str(base), env=env, stdout=game_log,
                                     stderr=subprocess.STDOUT)
            game_exit_code = child.wait()
    finally:
        if splash:
            splash.destroy()
        if voice_service:
            voice_service.close()
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
                server_proc.wait(timeout=8)
        model_log.close()

    # All game/AI processes and their file handles are now stopped. The separate
    # helper can replace Windows binaries only after this launcher fully exits.
    if pending_update.is_file():
        try:
            data = json.loads(pending_update.read_text(encoding="utf-8"))
            start_update_helper(base, data.get("tag", ""))
            pending_update.unlink()
            return 0
        except (ValueError, OSError, PortableSetupError) as exc:
            notify("Couldn't start the updater; your game is unchanged:\n\n" + str(exc),
                   error=True)
            return 1
    return game_exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, PortableSetupError, RuntimeSetupError) as exc:
        notify(f"Unable to start the portable game:\n\n{exc}", error=True)
        sys.exit(1)
