"""Opt-in GitHub release discovery for the portable, localhost-only game.

Normal gameplay performs no update network calls. A user must request a check,
then affirmatively choose to install. No GitHub account/token is required.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import threading
from urllib import request, error

REPOSITORY = "maloysius-wq/the-last-connection"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ASSET_NAME = "TheLastConnection-Windows-Portable.zip"
HASH_NAME = "SHA256SUMS.txt"
TAG_RE = re.compile(r"^portable-[0-9a-f]{40}$")
MAX_METADATA = 1_000_000


class UpdateError(RuntimeError):
    pass


def installed_tag(base: Path) -> str:
    try:
        data = json.loads((base / "build-info.json").read_text(encoding="utf-8"))
        return data.get("tag", "legacy") if isinstance(data.get("tag"), str) else "legacy"
    except (OSError, ValueError, TypeError):
        return "legacy"


def _json_url(url: str, opener=None) -> dict:
    opener = opener or request.urlopen
    req = request.Request(url, headers={
        "User-Agent": "TheLastConnection-Updater/1", "Accept": "application/vnd.github+json",
        "Cache-Control": "no-cache",
    })
    try:
        with opener(req, timeout=20) as response:
            data = response.read(MAX_METADATA + 1)
    except error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("No published game update is available yet.") from exc
        raise UpdateError(f"GitHub update check failed (HTTP {exc.code}).") from exc
    except (OSError, TimeoutError) as exc:
        raise UpdateError("Unable to reach GitHub. Check your connection and try again.") from exc
    if len(data) > MAX_METADATA:
        raise UpdateError("GitHub release response was unexpectedly large.")
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise UpdateError("GitHub returned invalid release metadata.") from exc
    if not isinstance(result, dict):
        raise UpdateError("Invalid GitHub release metadata.")
    return result


def _asset_url(tag: str, asset: dict, name: str) -> str:
    url = asset.get("browser_download_url", "")
    prefix = f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
    if asset.get("name") != name or url != prefix + name:
        raise UpdateError("Release asset did not match the expected official download.")
    return url


def fetch_latest_release(opener=None) -> dict:
    data = _json_url(RELEASE_API, opener=opener)
    tag = data.get("tag_name", "")
    if not isinstance(tag, str) or not TAG_RE.fullmatch(tag) or data.get("draft") or data.get("prerelease"):
        raise UpdateError("Latest GitHub release is not a supported stable portable build.")
    assets = {x.get("name"): x for x in data.get("assets", []) if isinstance(x, dict)}
    if ASSET_NAME not in assets or HASH_NAME not in assets:
        raise UpdateError("Published release does not contain its update ZIP and checksum.")
    archive = assets[ASSET_NAME]
    checksum = assets[HASH_NAME]
    download_url = _asset_url(tag, archive, ASSET_NAME)
    hash_url = _asset_url(tag, checksum, HASH_NAME)
    size = archive.get("size", 0)
    if not isinstance(size, int) or not 1_000_000 <= size <= 1_000_000_000:
        raise UpdateError("Update download has an unexpected size.")
    return {"tag": tag, "title": str(data.get("name") or tag)[:120],
            "size": size, "download_url": download_url, "checksum_url": hash_url}


class UpdateService:
    def __init__(self, base: Path, getter=fetch_latest_release):
        self.base = base
        self.getter = getter
        self._lock = threading.Lock()
        self._candidate: dict | None = None

    def check(self) -> dict:
        release = self.getter()
        current = installed_tag(self.base)
        with self._lock:
            self._candidate = release if release["tag"] != current else None
        return {"available": release["tag"] != current,
                "current": current, "latest": release["tag"],
                "title": release["title"], "size": release["size"]}

    def queue(self, tag: str) -> dict:
        with self._lock:
            if not self._candidate or tag != self._candidate["tag"]:
                raise UpdateError("Check for updates again before installing.")
            if not TAG_RE.fullmatch(tag):
                raise UpdateError("Invalid update identifier.")
            pending = self.base / "updates"
            pending.mkdir(parents=True, exist_ok=True)
            marker = pending / "request.json"
            temp = pending / "request.tmp"
            temp.write_text(json.dumps({"tag": tag}), encoding="utf-8")
            temp.replace(marker)
            return {"ok": True, "message": "Exit the game to install the selected update."}
