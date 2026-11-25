"""Standalone Windows updater executable. Runs outside the game's install folder.

It verifies GitHub release SHA-256, validates the ZIP, swaps folders only
*after* the game launcher is gone, preserves local data by same-volume moves,
rolls back on failure, and relaunches the game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
from urllib import request
import zipfile

from portable.update_service import ASSET_NAME, HASH_NAME, UpdateError, fetch_latest_release, TAG_RE

MAX_ARCHIVE = 1_000_000_000
MAX_UNPACKED = 2_000_000_000
PRESERVE = ("config.json", "user_data", "models", "logs")
REQUIRED = ("TheLastConnection.exe", "TheLastConnectionGame.exe",
            "TheLastConnectionUpdater.exe", "build-info.json")


def wait_for_parent(pid: int, seconds: int = 90) -> None:
    if os.name != "nt" or not pid:
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    SYNCHRONIZE = 0x00100000
    handle = kernel.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        # ERROR_INVALID_PARAMETER means the PID no longer exists. Access
        # denied is not proof the process has stopped.
        if ctypes.get_last_error() == 87:
            return
        raise UpdateError("Cannot confirm the game has closed. Close it and retry the update.")
    try:
        if kernel.WaitForSingleObject(handle, seconds * 1000) != 0:
            raise UpdateError("The game is still open or could not be checked. Close it to finish updating.")
    finally:
        kernel.CloseHandle(handle)


def _response_download(url: str, target: Path, expected_size: int, progress=None, opener=None) -> None:
    opener = opener or request.urlopen
    if not url.startswith("https://github.com/maloysius-wq/the-last-connection/releases/download/"):
        raise UpdateError("Refusing an update from an unknown location.")
    req = request.Request(url, headers={"User-Agent": "TheLastConnection-Updater/1"})
    total = 0
    with opener(req, timeout=60) as response, target.open("wb") as out:
        final_url = response.geturl() if hasattr(response, "geturl") else url
        if not final_url.startswith("https://"):
            raise UpdateError("Update server redirected to an insecure connection.")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARCHIVE:
                raise UpdateError("Update ZIP is unexpectedly large.")
            out.write(chunk)
            if progress:
                progress(f"Downloading update: {total // 1_000_000} MB")
    if total != expected_size:
        raise UpdateError("The download was incomplete. The existing game was not changed.")


def _read_hash(url: str, opener=None) -> str:
    opener = opener or request.urlopen
    if not url.startswith("https://github.com/maloysius-wq/the-last-connection/releases/download/"):
        raise UpdateError("Untrusted checksum location.")
    with opener(request.Request(url, headers={"User-Agent": "TheLastConnection-Updater/1"}), timeout=20) as resp:
        data = resp.read(2048)
    matches = re.findall(r"^([0-9a-fA-F]{64})\s+\*?" + re.escape(ASSET_NAME) + r"\s*$", data.decode("utf-8"), re.M)
    if len(matches) != 1:
        raise UpdateError("Update checksum was missing or invalid.")
    return matches[0].lower()


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while data := handle.read(1024 * 1024):
            value.update(data)
    return value.hexdigest()


def unpack_verified(archive: Path, staging: Path, expected_tag: str) -> None:
    staging.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as zf:
        if zf.testzip() is not None:
            raise UpdateError("Downloaded archive is corrupted.")
        members = zf.infolist()
        if len(members) > 20_000 or sum(info.file_size for info in members) > MAX_UNPACKED:
            raise UpdateError("Update archive exceeds safe size limits.")
        for info in members:
            rel = PurePosixPath(info.filename.replace("\\", "/"))
            # Reject traversal, absolute paths, Windows drive syntax and symlinks.
            if (not info.filename or rel.is_absolute() or ".." in rel.parts
                    or ":" in info.filename or not rel.parts or rel.parts[0] in ("", ".")):
                raise UpdateError("Unsafe file path inside update archive.")
            if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise UpdateError("Update archive contains an unsupported symbolic link.")
            if rel.parts[0] in PRESERVE or rel.parts[0] in ("updates", "temp"):
                raise UpdateError("Update archive attempted to replace private user data.")
        zf.extractall(staging)
    for name in REQUIRED:
        if not (staging / name).is_file():
            raise UpdateError("Incomplete release archive: missing " + name)
    for name in ("TheLastConnection.exe", "TheLastConnectionGame.exe", "TheLastConnectionUpdater.exe"):
        with (staging / name).open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise UpdateError("Invalid Windows executable in the update.")
    try:
        meta = json.loads((staging / "build-info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpdateError("Updated version metadata is missing or corrupt.") from exc
    if meta.get("tag") != expected_tag:
        raise UpdateError("The update build version did not match the release.")
    if not any((staging / "runtime/llama" / mode / "llama-server.exe").is_file() for mode in ("cpu", "vulkan")):
        raise UpdateError("Update lacks an inference runtime.")


def rename_with_retry(source: Path, destination: Path, progress=None, *, attempts: int = 31) -> None:
    """Allow Windows time to release transient file/working-directory locks.

    Never overwrite an existing destination, escalate permissions, or kill
    an unrelated process. Permanent access denial leaves the source intact.
    """
    for attempt in range(attempts):
        if destination.exists():
            raise UpdateError("Refusing to overwrite existing update path: " + str(destination))
        try:
            source.rename(destination)
            return
        except OSError as exc:
            retryable = isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in (5, 32, 33)
            if not retryable:
                raise
            if attempt + 1 == attempts:
                raise UpdateError(
                    "Windows would not release the folder or file: " + str(source) +
                    ". Close game-related processes, Explorer windows and terminals using this folder, "
                    "or restart Windows, then retry. Original error: " + str(exc)
                ) from exc
            if progress and attempt % 5 == 0:
                progress("Waiting for Windows to release " + source.name + "...")
            time.sleep(1)


def install_staged(base: Path, staging: Path, backup: Path, progress=None) -> None:
    """Same-volume atomic renames where available, with explicit rollback."""
    if backup.exists():
        raise UpdateError("An older update backup exists. Do not overwrite it automatically.")
    for name in REQUIRED[:2]:
        if not (base / name).is_file():
            raise UpdateError("This isn't a valid The Last Connection installation.")
    old_moved = False
    new_moved = False
    preserved: list[str] = []
    try:
        rename_with_retry(base, backup, progress)
        old_moved = True
        rename_with_retry(staging, base, progress)
        new_moved = True
        for name in PRESERVE:
            source = backup / name
            if source.exists():
                if (base / name).exists():
                    raise UpdateError("New release collides with saved user data: " + name)
                rename_with_retry(source, base / name, progress)
                preserved.append(name)
    except Exception:
        if old_moved:
            for name in reversed(preserved):
                source = base / name
                if source.exists():
                    rename_with_retry(source, backup / name, progress)
            if new_moved and base.exists():
                shutil.rmtree(base)
            if backup.exists():
                rename_with_retry(backup, base, progress)
        raise
    if backup.exists():
        try:
            shutil.rmtree(backup)
        except OSError:
            # A successful upgrade is not undone just because stale old binaries
            # could not be deleted. Leave for manual cleanup.
            pass


def run_update(base: Path, tag: str, progress=None, getter=fetch_latest_release,
               downloader=_response_download, reader=_read_hash) -> None:
    if not TAG_RE.fullmatch(tag):
        raise UpdateError("Invalid update tag.")
    base = base.resolve()
    if not base.is_dir() or not (base / "TheLastConnection.exe").is_file():
        raise UpdateError("Invalid game installation folder.")
    release = getter()
    if release["tag"] != tag:
        raise UpdateError("A newer release is available. Check for updates again.")
    stage = base.parent / (".TheLastConnection-staging-" + str(os.getpid()))
    archive = base.parent / (".TheLastConnection-download-" + str(os.getpid()) + ".zip")
    backup = base.parent / ".TheLastConnection-previous"
    if backup.exists() or stage.exists():
        raise UpdateError("An older update staging or backup folder exists. Resolve it before installing.")
    try:
        downloader(release["download_url"], archive, release["size"], progress)
        if progress:
            progress("Verifying SHA-256 checksum...")
        if _sha256(archive) != reader(release["checksum_url"]):
            raise UpdateError("Update checksum did not match. Nothing was installed.")
        if progress:
            progress("Checking archive and preparing installation...")
        unpack_verified(archive, stage, tag)
        if progress:
            progress("Installing update and protecting your saves...")
        install_staged(base, stage, backup, progress)
    finally:
        if archive.exists():
            archive.unlink()
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def _show_error(message: str) -> None:
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "The Last Connection Update", 0x10)
    else:
        print(message, file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--parent-pid", type=int, default=0)
    args = parser.parse_args()
    base = Path(args.base).resolve()
    # A manually started helper must not hold the game folder as its CWD.
    os.chdir(base.parent)
    log_path = base.parent / ".TheLastConnection-update.log"
    def log(message: str) -> None:
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + message + "\n")
        except OSError:
            pass
    window = None
    label = None
    def progress(message: str) -> None:
        log(message)
        if window:
            label.config(text=message)
            window.update()
    try:
        if os.name == "nt":
            import tkinter
            window = tkinter.Tk()
            window.title("The Last Connection | Updating")
            window.geometry("480x120")
            window.resizable(False, False)
            label = tkinter.Label(window, text="Preparing your update...", font=("Segoe UI", 10), wraplength=450)
            label.pack(padx=15, pady=30)
            window.update()
        log("Starting update " + args.tag)
        wait_for_parent(args.parent_pid)
        run_update(base, args.tag, progress=progress)
        log("Installation completed successfully.")
        if window:
            window.destroy()
        subprocess.Popen([str(base / "TheLastConnection.exe")], cwd=str(base))
        return 0
    except Exception as exc:
        log("Update failed: " + repr(exc))
        if window:
            window.destroy()
        _show_error(f"Update failed. Your existing game and saved data should be preserved.\n\n{exc}\n\nDiagnostics: {log_path}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
