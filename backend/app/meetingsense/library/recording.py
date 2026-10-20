"""A live meeting's own recording: received in pieces while the call runs, kept with the meeting.

The recorder (``public/js/homepilot-meetingsense.js``) taps the same gain nodes the transcriber
listens to — the call and the microphone, so muting the microphone mutes the recording too —
and records them with ``MediaRecorder``. Every few seconds it posts the piece it has:
``POST /v1/meetingsense/library/item/{id}/recording?seq=N``. Uploading while the meeting runs is
what makes a closed tab or a crashed browser cost seconds rather than the meeting.

The pieces of one ``MediaRecorder`` are one file: the first carries the container header and
the rest only make sense after it. So they are appended strictly in order — ``seq`` is the
order, a repeat is acknowledged and dropped, a gap is refused with the number expected — to
``<media_root>/<meeting_id>/recording.<ext>.part``. On ``complete``, or once the meeting has
ended and the pieces have stopped coming (``finalize_stale``), the file is remuxed by FFmpeg so
it carries a duration and a seek index, and registered as the meeting's audio asset. From then
on it is an ordinary library recording: the Meeting details player, download and delete all
work on it unchanged.

Kept only for a meeting whose retention keeps audio (``all``) — decided once, when it starts:
``MEETINGSENSE_RETENTION`` when the operator set it, otherwise the user's Settings → Meetings
choice (``retention.meeting_retention``).

The recording's clock: segment times are the browser's capture clock, which starts with the
audio graph and keeps counting across a reconnect. ``offset_ms`` is where on that clock this
recording began, stored on the asset, so the player can line every transcript line up with it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import store
from . import db, media
from .config import media_root

log = logging.getLogger(__name__)

#: The largest single piece accepted. A five-second Opus slice is tens of kilobytes; this is
#: room for a slow browser that hands over a long slice at once, not for a file upload.
CHUNK_MAX_BYTES = 8 * 1024 * 1024
#: Pieces are still accepted this long after the meeting ended: the last slices of the call
#: are posted after the stop, and a reconnect can be holding a few more.
TAIL_GRACE_S = 600
#: An upload with no new piece for this long, on a meeting no longer live, is complete.
IDLE_FINALIZE_S = 30

STATE_FILE = "recording.json"
SOURCE_ID = "meetingsense-live"

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
#: Container signatures → (extension, MIME type, FFmpeg muxer). The browser's declared type is
#: a hint; the first bytes are the check.
_CONTAINERS = (
    (b"\x1a\x45\xdf\xa3", ("webm", "audio/webm", "webm")),
    (b"OggS", ("ogg", "audio/ogg", "ogg")),
)

_locks_guard = threading.Lock()
_locks: Dict[str, threading.Lock] = {}


class RecordingError(Exception):
    """A piece or a completion refused, with an HTTP status and a stable code."""

    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def body(self) -> Dict[str, Any]:
        return {"detail": {"code": self.code, "message": self.message, **self.extra}}


def max_total_bytes() -> int:
    """The most one meeting's recording may grow to (``MEETINGS_RECORDING_MAX_MB``, default 4 GB
    — over a hundred hours of the browser's Opus)."""
    try:
        mb = int(os.getenv("MEETINGS_RECORDING_MAX_MB", "4096").strip() or "4096")
    except ValueError:
        mb = 4096
    return max(1, mb) * 1024 * 1024


def _lock(meeting_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(meeting_id)
        if lock is None:
            lock = _locks[meeting_id] = threading.Lock()
        return lock


def _folder(meeting_id: str) -> Path:
    if not _ID.match(meeting_id or ""):
        raise RecordingError(404, "not_found", "not found")
    root = media_root().resolve()
    folder = (root / meeting_id).resolve()
    if folder.parent != root:
        raise RecordingError(404, "not_found", "not found")
    return folder


def _read_state(folder: Path) -> Dict[str, Any]:
    try:
        return json.loads((folder / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(folder: Path, state: Dict[str, Any]) -> None:
    tmp = folder / f"{STATE_FILE}.tmp"
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(folder / STATE_FILE)


def _container(head: bytes) -> Optional[tuple]:
    for magic, kind in _CONTAINERS:
        if head.startswith(magic):
            return kind
    if head[4:8] == b"ftyp":  # Safari records MP4/AAC
        return ("m4a", "audio/mp4", "mp4")
    return None


def _ended_too_long_ago(meeting: Dict[str, Any], now: float) -> bool:
    if (meeting.get("status") or "") in ("live", "suspended"):
        return False
    ended = meeting.get("ended_at")
    return not ended or now - float(ended) > TAIL_GRACE_S


def append(meeting_id: str, seq: int, data: bytes, *, mime: str = "", offset_ms: int = 0,
           now: Optional[float] = None) -> Dict[str, Any]:
    """Add piece ``seq`` to the meeting's recording. Idempotent for a repeated piece."""
    now = time.time() if now is None else now
    meeting = store.get_meeting(meeting_id)
    if meeting is None:
        raise RecordingError(404, "not_found", "not found")
    if (meeting.get("retention") or "text") != "all":
        raise RecordingError(409, "not_kept", "This meeting keeps only its transcript, not the audio.")
    if _ended_too_long_ago(meeting, now):
        raise RecordingError(410, "closed", "This meeting ended too long ago to add to its recording.")
    if not data:
        raise RecordingError(400, "empty", "The piece was empty.")
    if len(data) > CHUNK_MAX_BYTES:
        raise RecordingError(413, "too_large", "That piece is too large.")
    folder = _folder(meeting_id)
    with _lock(meeting_id):
        state = _read_state(folder) if folder.is_dir() else {}
        if state.get("finalized"):
            raise RecordingError(409, "finalized", "This recording is already complete.")
        expected = int(state.get("next_seq") or 0)
        if seq < expected:
            return {"ok": True, "next_seq": expected, "duplicate": True}
        if seq > expected:
            raise RecordingError(409, "out_of_order", "A piece is missing before this one.", expected=expected)
        if seq == 0:
            kind = _container(data[:16])
            if kind is None:
                raise RecordingError(415, "not_audio", "The recording is not in a format HomePilot keeps.")
            ext, sniffed_mime, muxer = kind
            folder.mkdir(parents=True, exist_ok=True)
            state = {
                "ext": ext, "mime": sniffed_mime, "muxer": muxer,
                "declared_mime": (mime or "")[:120], "offset_ms": max(0, int(offset_ms or 0)),
                "bytes": 0, "chunks": 0, "next_seq": 0, "started_at": now,
            }
            (folder / f"recording.{ext}.part").write_bytes(b"")
            db.ensure_entry(meeting_id)
            db.update_entry(meeting_id, recording_state="uploading")
        elif int(state.get("bytes") or 0) + len(data) > max_total_bytes():
            raise RecordingError(413, "too_large", "This recording has reached the size limit.")
        part = folder / f"recording.{state['ext']}.part"
        with open(part, "ab") as fh:
            fh.write(data)
        state.update(next_seq=seq + 1, bytes=int(state.get("bytes") or 0) + len(data),
                     chunks=int(state.get("chunks") or 0) + 1, updated_at=now)
        _write_state(folder, state)
    return {"ok": True, "next_seq": seq + 1}


def _remux(part: Path, final: Path, muxer: str) -> bool:
    """Rewrite the stitched pieces as one file with a duration and seek index (stream copy,
    no re-encoding). False when FFmpeg is missing or cannot read it — the pieces are then kept
    as they are, which browsers still play."""
    if not shutil.which("ffmpeg"):
        return False
    tmp = final.with_name(final.name + ".tmp")
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(part), "-map", "0:a",
            "-c", "copy"]
    if muxer == "mp4":
        args += ["-movflags", "+faststart"]
    args += ["-f", muxer, str(tmp)]
    try:
        res = subprocess.run(args, capture_output=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired):
        tmp.unlink(missing_ok=True)
        return False
    if res.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        log.warning("meetingsense: could not remux the recording %s: %s", part,
                    (res.stderr or b"").decode("utf-8", errors="replace")[:300])
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(final)
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_name(title: str, ext: str) -> str:
    stem = re.sub(r"[^\w\- ]+", "", title or "").strip()[:80] or "Meeting recording"
    return f"{stem}.{ext}"


def finalize(meeting_id: str) -> Optional[Dict[str, Any]]:
    """Close the recording and register it as the meeting's audio. Idempotent; ``None`` when
    there is nothing recorded."""
    folder = _folder(meeting_id)
    with _lock(meeting_id):
        state = _read_state(folder) if folder.is_dir() else {}
        if not state:
            return None
        if state.get("finalized"):
            return db.get_asset(state.get("asset_id") or "")
        ext = state.get("ext") or "webm"
        part = folder / f"recording.{ext}.part"
        if not part.is_file() or part.stat().st_size == 0:
            part.unlink(missing_ok=True)
            (folder / STATE_FILE).unlink(missing_ok=True)
            db.update_entry(meeting_id, recording_state="none")
            return None
        final = folder / f"recording.{ext}"
        if _remux(part, final, state.get("muxer") or "webm"):
            part.unlink(missing_ok=True)
        else:
            part.replace(final)
        meeting = store.get_meeting(meeting_id) or {}
        info = media.probe(final)
        duration_ms = info.get("duration_ms") if info.get("ok") else None
        if not duration_ms and meeting.get("started_at") and meeting.get("ended_at"):
            duration_ms = max(0, int((float(meeting["ended_at"]) - float(meeting["started_at"])) * 1000)
                              - int(state.get("offset_ms") or 0))
        asset_id = db.add_asset(
            meeting_id=meeting_id, source_id=SOURCE_ID, origin_type="meetingsense",
            relative_path=final.name, original_name=_file_name(meeting.get("title") or "", ext),
            kind="audio", role="primary", sha256=_sha256(final), mime=state.get("mime") or "audio/webm",
            size_bytes=final.stat().st_size, storage_ref=f"{meeting_id}/{final.name}",
            media_duration_ms=duration_ms or None,
            metadata={
                "recorded": "live", "offset_ms": int(state.get("offset_ms") or 0),
                "codec": info.get("codec"), "chunks": int(state.get("chunks") or 0),
                "declared_mime": state.get("declared_mime") or None,
            },
        )
        db.ensure_entry(meeting_id)
        db.update_entry(meeting_id, media_present=1, recording_state="present")
        state.update(finalized=True, asset_id=asset_id, finalized_at=time.time())
        _write_state(folder, state)
        return db.get_asset(asset_id)


def finalize_stale(now: Optional[float] = None) -> List[str]:
    """Complete every recording whose browser never said so: the meeting is no longer live and
    nothing has arrived for ``IDLE_FINALIZE_S``. Called when the library is read. Never raises."""
    now = time.time() if now is None else now
    done: List[str] = []
    try:
        pending = db.meetings_with_recording_state("uploading")
    except Exception:  # noqa: BLE001
        return done
    for meeting_id in pending:
        try:
            meeting = store.get_meeting(meeting_id)
            if meeting is None:
                db.update_entry(meeting_id, recording_state="none")
                continue
            if (meeting.get("status") or "") in ("live", "suspended"):
                continue
            state = _read_state(_folder(meeting_id))
            last = float(state.get("updated_at") or state.get("started_at") or 0)
            if now - last < IDLE_FINALIZE_S:
                continue
            finalize(meeting_id)
            done.append(meeting_id)
        except Exception:  # noqa: BLE001 — one bad recording must not hide the library
            log.exception("meetingsense: could not complete the recording for %s", meeting_id)
    return done
