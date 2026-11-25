"""Security and preservation tests for opt-in portable game updates."""
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from portable.update_service import (ASSET_NAME, HASH_NAME, REPOSITORY, UpdateError,
                                    UpdateService, fetch_latest_release, installed_tag)
from portable.updater import (install_staged, unpack_verified, run_update, _sha256, rename_with_retry)

TAG = "portable-" + "1" * 40
NAME = ASSET_NAME
ROOT = f"https://github.com/{REPOSITORY}/releases/download/{TAG}/"


def release(tag=TAG):
    return {"tag_name": tag, "draft": False, "prerelease": False,
            "name": "Game update", "assets": [
        {"name": NAME, "browser_download_url": ROOT + NAME, "size": 50_000_000},
        {"name": HASH_NAME, "browser_download_url": ROOT + HASH_NAME, "size": 200},
    ]}


class FakeResponse:
    def __init__(self, data):
        self.data = io.BytesIO(data)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, amount=-1):
        return self.data.read(amount)


def zip_release(path: Path, tag=TAG, extras=None):
    with zipfile.ZipFile(path, "w") as zf:
        for name in ("TheLastConnection.exe", "TheLastConnectionGame.exe", "TheLastConnectionUpdater.exe"):
            zf.writestr(name, b"MZ" + b"x" * 1024)
        zf.writestr("runtime/llama/cpu/llama-server.exe", b"MZ")
        zf.writestr("build-info.json", json.dumps({"tag": tag}))
        for name, content in (extras or {}).items():
            zf.writestr(name, content)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.base = self.home / "TheLastConnection"
        self.base.mkdir()
        (self.base / "TheLastConnection.exe").write_bytes(b"MZold")
        (self.base / "TheLastConnectionGame.exe").write_bytes(b"MZold")

    def tearDown(self):
        self.temp.cleanup()

    def test_release_metadata_requires_official_assets(self):
        raw = json.dumps(release()).encode()
        data = fetch_latest_release(opener=lambda *args, **kw: FakeResponse(raw))
        self.assertEqual(data["tag"], TAG)
        self.assertEqual(data["size"], 50_000_000)
        bad = release()
        bad["assets"][0]["browser_download_url"] = "https://evil.example/update.zip"
        with self.assertRaises(UpdateError):
            fetch_latest_release(opener=lambda *args, **kw: FakeResponse(json.dumps(bad).encode()))

    def test_check_does_not_queue_or_download(self):
        calls = []
        service = UpdateService(self.base, getter=lambda: (calls.append("get") or
                               {"tag": TAG, "title": "Game Update", "size": 500}))
        state = service.check()
        self.assertTrue(state["available"])
        self.assertEqual(calls, ["get"])
        self.assertFalse((self.base / "updates").exists())
        with self.assertRaises(UpdateError):
            service.queue("portable-" + "2" * 40)
        service.queue(TAG)
        self.assertEqual(json.loads((self.base / "updates/request.json").read_text())["tag"], TAG)

    def test_cannot_install_without_check(self):
        service = UpdateService(self.base, getter=lambda: {})
        with self.assertRaises(UpdateError):
            service.queue(TAG)

    def test_already_current_release(self):
        (self.base / "build-info.json").write_text(json.dumps({"tag": TAG}))
        self.assertEqual(installed_tag(self.base), TAG)
        service = UpdateService(self.base, getter=lambda: {"tag": TAG, "title": "Current", "size": 1})
        self.assertFalse(service.check()["available"])
        with self.assertRaises(UpdateError):
            service.queue(TAG)

    def test_unpack_rejects_path_traversal_and_private_files(self):
        for name in ("../escape.txt", "/outside.txt", "models/private.gguf", "user_data/save.json", "C:escape", "updates/request.json"):
            with self.subTest(name=name):
                src = self.home / "release.zip"
                zip_release(src, extras={name: "attack"})
                stage = self.home / "stage"
                with self.assertRaises(UpdateError):
                    unpack_verified(src, stage, TAG)
                if stage.exists():
                    import shutil
                    shutil.rmtree(stage)

    def test_rejects_wrong_build_metadata(self):
        src = self.home / "release.zip"
        zip_release(src, tag="portable-" + "2" * 40)
        with self.assertRaises(UpdateError):
            unpack_verified(src, self.home / "stage", TAG)

    def test_swaps_game_without_copying_user_model_or_resetting_save(self):
        (self.base / "config.json").write_text('{"model_path":"D:/models/eli.gguf"}')
        (self.base / "user_data").mkdir()
        (self.base / "user_data/save.txt").write_text("progress")
        (self.base / "models").mkdir()
        (self.base / "models/eli.gguf").write_bytes(b"GGUF" + b"x" * 1000)
        archive = self.home / "release.zip"
        zip_release(archive)
        stage = self.home / "stage"
        unpack_verified(archive, stage, TAG)
        install_staged(self.base, stage, self.home / "backup")
        self.assertEqual((self.base / "user_data/save.txt").read_text(), "progress")
        self.assertIn("D:/models", (self.base / "config.json").read_text())
        self.assertEqual((self.base / "models/eli.gguf").stat().st_size, 1004)
        self.assertEqual(json.loads((self.base / "build-info.json").read_text())["tag"], TAG)
        self.assertFalse((self.home / "backup").exists())

    def test_transient_windows_lock_retries_and_preserves_installation(self):
        archive = self.home / "release.zip"
        zip_release(archive)
        stage = self.home / "stage"
        backup = self.home / "backup"
        unpack_verified(archive, stage, TAG)
        (self.base / "config.json").write_text("saved configuration")
        original = Path.rename
        blocked = []
        def flaky(path, dest):
            if path == self.base and not blocked:
                blocked.append(True)
                raise PermissionError(13, "Windows is holding the folder")
            return original(path, dest)
        with patch.object(Path, "rename", flaky), patch("portable.updater.time.sleep") as delay:
            install_staged(self.base, stage, backup)
        delay.assert_called_once_with(1)
        self.assertEqual((self.base / "config.json").read_text(), "saved configuration")
        self.assertFalse(backup.exists())
        self.assertEqual(json.loads((self.base / "build-info.json").read_text())["tag"], TAG)

    def test_persistent_directory_lock_does_not_move_original(self):
        backup = self.home / "backup"
        with patch.object(Path, "rename", side_effect=PermissionError(13, "locked")), patch("portable.updater.time.sleep") as delay:
            with self.assertRaisesRegex(UpdateError, "Windows would not release"):
                rename_with_retry(self.base, backup, attempts=3)
        self.assertEqual(delay.call_count, 2)
        self.assertEqual((self.base / "TheLastConnection.exe").read_bytes(), b"MZold")
        self.assertFalse(backup.exists())

    def test_rename_refuses_existing_destination(self):
        backup = self.home / "backup"
        backup.mkdir()
        with self.assertRaisesRegex(UpdateError, "Refusing to overwrite"):
            rename_with_retry(self.base, backup)
        self.assertTrue(self.base.is_dir())

    def test_bad_checksum_does_not_modify_game(self):
        archive = self.home / "local_release.zip"
        zip_release(archive)
        metadata = {"tag": TAG, "download_url": ROOT + NAME, "checksum_url": ROOT + HASH_NAME,
                    "size": archive.stat().st_size}
        def downloader(url, destination, expected, progress=None):
            destination.write_bytes(archive.read_bytes())
        with self.assertRaises(UpdateError):
            run_update(self.base, TAG, getter=lambda: metadata,
                       downloader=downloader, reader=lambda _: "0" * 64)
        self.assertEqual((self.base / "TheLastConnection.exe").read_bytes(), b"MZold")
        self.assertFalse(any(x.name.startswith(".TheLastConnection-staging") for x in self.home.iterdir()))

    def test_verified_download_and_install(self):
        archive = self.home / "local_release.zip"
        zip_release(archive)
        metadata = {"tag": TAG, "download_url": ROOT + NAME, "checksum_url": ROOT + HASH_NAME,
                    "size": archive.stat().st_size}
        def downloader(url, destination, expected, progress=None):
            destination.write_bytes(archive.read_bytes())
        run_update(self.base, TAG, getter=lambda: metadata,
                   downloader=downloader, reader=lambda _: _sha256(archive))
        self.assertTrue((self.base / "TheLastConnectionUpdater.exe").is_file())
        self.assertTrue((self.base / "runtime/llama/cpu/llama-server.exe").is_file())


if __name__ == "__main__":
    unittest.main()
