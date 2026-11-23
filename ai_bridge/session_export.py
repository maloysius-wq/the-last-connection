"""Create a self-contained bug-report ZIP for the player's current session.

User action only. The resulting archive contains the displayed chat, local
per-session model/validation/action diagnostics and a bounded saved state.
No voice recordings, model files, tokens, environment variables or other
players' session histories are included.
"""
from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import zipfile

from .agent import SessionStore, InvalidRequest

MAX_TRANSCRIPT = 500_000
MAX_ARCHIVE = 2_000_000


def build_session_archive(store: SessionStore, session_id: str,
                          transcript: str, world: dict) -> bytes:
    # SessionStore validates IDs and confines all reads to its private folder.
    path = store._path(session_id)
    if not isinstance(transcript, str) or len(transcript) > MAX_TRANSCRIPT:
        raise InvalidRequest("The conversation is too long to export in one file.")
    if not isinstance(world, dict) or len(json.dumps(world)) > 12_000:
        raise InvalidRequest("Invalid room state in export request.")
    state = store.load(session_id)
    events = store.trace_path(session_id)
    trace_data = events.read_bytes()[-1_500_000:] if events.is_file() else b""
    # Avoid starting on a truncated partial JSON line after bounded tail.
    if len(trace_data) == 1_500_000:
        newline = trace_data.find(b"\n")
        trace_data = trace_data[newline+1:] if newline >= 0 else b""
    notes = (
        "THE LAST CONNECTION / SESSION REPORT\n\n"
        "Created by pressing EXPORT CONVERSATION + LOGS in the game.\n"
        "Upload this ZIP to ChatGPT to reproduce difficult Eli interactions.\n\n"
        "conversation.txt: full visible UI transcript at time of export.\n"
        "diagnostics.jsonl: local event-by-event player inputs, structured model\n"
        "interpretations, plan reviews, chosen actions, and verified outcomes.\n"
        "conversation_state.json: compact backend history and confirmed facts.\n"
        "current_room.json: authoritative world state at export time.\n\n"
        "PRIVACY: You are choosing to share these data. They contain everything\n"
        "you typed to Eli and may contain details from your conversation.\n"
        "No microphone audio, speech models, or passwords are bundled.\n"
        "No export is automatically uploaded anywhere.\n"
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=7) as out:
        # Fixed internal paths prevent ZIP path traversal and filename tricks.
        out.writestr("README.txt", notes)
        out.writestr("conversation.txt", transcript)
        out.writestr("diagnostics.jsonl", trace_data)
        out.writestr("conversation_state.json",
                     json.dumps(state, ensure_ascii=False, indent=2))
        out.writestr("current_room.json",
                     json.dumps(world, ensure_ascii=False, indent=2))
        out.writestr("export_manifest.json", json.dumps({
            "session_id": session_id,
            "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "format": 1,
            "diagnostics_included": bool(trace_data),
            "saved_state_present": path.is_file(),
        }, indent=2))
    data = archive.getvalue()
    if len(data) > MAX_ARCHIVE:
        raise InvalidRequest("This session archive is too large to transfer.")
    return data
