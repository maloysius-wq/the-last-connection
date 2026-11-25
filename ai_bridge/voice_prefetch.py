"""Bounded speculative first-chunk TTS. No unvalidated audio leaves the bridge."""
from __future__ import annotations

import threading
import time
import uuid


def first_voice_chunk(speech, fast=True):
    """Mirror Godot's first chunk; exact match is required at commit and playback."""
    current = ""
    limit = 72 if fast else 420
    for word in speech.split(" "):
        if not word:
            continue
        if len(word) > 420:
            return current or word[:420]
        if current and len(current) + len(word) + 1 > limit:
            return current
        current += (" " if current else "") + word
        if fast and (word.endswith((".", "!", "?")) or
                     (len(current) >= 35 and word.endswith((",", ";")))):
            return current
    return current


class VoicePrefetch:
    def __init__(self, voice):
        self.voice = voice
        self.synthesis_lock = threading.Lock()
        self._lock = threading.Lock()
        self._job = None

    def offer(self, speech, emotion, options):
        # Only the selected, already-warmed official CUDA worker. No fallback
        # or speculative allocation of another engine, and at most one job.
        if not isinstance(options, dict) or self.voice is None:
            return None
        settings = getattr(self.voice, "startup_report", None)
        if not isinstance(settings, dict) or settings.get("status") != "ready" or settings.get("engine") != "nano_cuda":
            return None
        requested = {k: options.get(k) for k in ("engine", "profile", "threads")}
        if requested != settings.get("settings") or type(options.get("fast")) is not bool:
            return None
        chunk = first_voice_chunk(speech, options["fast"])
        if not chunk or len(chunk) > 420:
            return None
        with self._lock:
            if self._job is not None and not self._job["done"].is_set():
                return None
            if not self.synthesis_lock.acquire(blocking=False):
                return None
            job = {"id": uuid.uuid4().hex, "text": chunk, "emotion": emotion,
                   "options": requested, "fast": options["fast"], "done": threading.Event(),
                   "audio": None, "approved": False, "created": time.monotonic()}
            self._job = job
            def work():
                try:
                    audio = self.voice.synthesize(chunk, emotion, warmup_only=True, **requested)
                    if self.voice.last_engine == "nano_cuda":
                        job["audio"] = audio
                except Exception:
                    pass
                finally:
                    job["done"].set()
                    self.synthesis_lock.release()
            threading.Thread(target=work, daemon=True).start()
            return job["id"]

    def approve(self, ticket, decision):
        with self._lock:
            job = self._job
            if not ticket or not job or job["id"] != ticket:
                return ""
            # Never play draft speech, a discarded repair, or a rejected plan.
            if (decision.actions or decision.status or
                    decision.emotion != job["emotion"] or
                    first_voice_chunk(decision.speech, job["fast"]) != job["text"]):
                self._job = None if job["done"].is_set() else job
                return ""
            job["approved"] = True
            return ticket

    def take(self, ticket, speech, emotion, options):
        with self._lock:
            job = self._job
            if (not isinstance(ticket, str) or not job or job["id"] != ticket or
                    not job["approved"] or job["text"] != speech or job["emotion"] != emotion or
                    job["options"] != options or time.monotonic() - job["created"] > 90):
                return None
            job["approved"] = False  # one use only
        if not job["done"].wait(timeout=80):
            return None
        with self._lock:
            if self._job is job:
                self._job = None
        return job["audio"]
