"""Meetings Library configuration — its own rollout gate, separate from MeetingSense's.

``MEETINGS_LIBRARY_UPGRADE`` turns on the unified library, imports, folder sync and offline
transcription. It defaults **off**: with it off the Meetings view, its routes and the live
recorder are exactly what they were, and turning it off again leaves every table and file the
upgrade wrote where it is, ready for the next time it is turned on.

Kept out of ``meetingsense.config`` on purpose: that module's key set is frozen by a test,
and a rollout gate that has to be removable must not be woven into the config it sits beside.

Folder sync reads the host's disk, so it is allowed only below roots the *operator* lists in
``MEETINGS_SYNC_ALLOWED_ROOTS``. A path typed into the browser grants nothing by itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _roots(raw: str) -> Tuple[str, ...]:
    """Allowed sync roots: separated by ``;`` or newlines (``:`` would split ``D:\\``)."""
    out: List[str] = []
    for part in raw.replace("\n", ";").split(";"):
        part = part.strip()
        if part:
            out.append(part)
    return tuple(out)


#: Where a Windows install keeps Insta360 / AIRecord recordings. A suggestion for the
#: Folder Sync form, never a path the server reads on its own.
DEFAULT_SYNC_SUGGESTION = "D:\\AIRecord"


@dataclass(frozen=True)
class LibraryConfig:
    enabled: bool = False
    #: Offline transcription and summaries for imported recordings. On with the library;
    #: separate so an operator can keep imports but stop all background inference.
    processing: bool = True
    sync_roots: Tuple[str, ...] = ()
    #: Upper bound for one uploaded file (MB). Meetings are long; an hour of 128 kb/s MP3
    #: is ~60 MB and an hour of WAV ~600 MB.
    max_upload_mb: int = 2048
    #: Seconds of audio per transcription chunk — bounds memory on long recordings and gives
    #: the Processing view progress it can show.
    stt_chunk_s: int = 300
    #: How often enabled folder sources are reconciled.
    sync_interval_s: int = 60
    #: A file must keep its size and mtime this long before it is imported, so a recording
    #: still being written is never indexed half-finished.
    stability_s: int = 10

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "processing": self.processing,
            "sync": bool(self.sync_roots),
            "sync_suggestion": DEFAULT_SYNC_SUGGESTION,
            "max_upload_mb": self.max_upload_mb,
        }


def load_library_config() -> LibraryConfig:
    """Read per call, like ``meetingsense.config.load_config``, so tests can vary it."""
    return LibraryConfig(
        enabled=_flag("MEETINGS_LIBRARY_UPGRADE", False),
        processing=_flag("MEETINGS_LIBRARY_PROCESSING", True),
        sync_roots=_roots(os.getenv("MEETINGS_SYNC_ALLOWED_ROOTS", "")),
        max_upload_mb=max(1, _int("MEETINGS_IMPORT_MAX_MB", 2048)),
        stt_chunk_s=max(30, _int("MEETINGS_STT_CHUNK_S", 300)),
        sync_interval_s=max(5, _int("MEETINGS_SYNC_INTERVAL_S", 60)),
        stability_s=max(0, _int("MEETINGS_SYNC_STABILITY_S", 10)),
    )


def media_root() -> Path:
    """HomePilot-owned storage for imported meeting files.

    A sibling of the uploads directory rather than inside it, so meeting audio is never
    reachable through the generic ``/files/`` route — it is served only by the library's own
    media route, which checks who is asking.
    """
    override = os.getenv("MEETINGS_LIBRARY_DIR", "").strip()
    if override:
        root = Path(override)
    else:
        from ...files import _upload_root  # noqa: PLC0415 — keep import-light

        root = _upload_root().parent / "meetings_library"
    root.mkdir(parents=True, exist_ok=True)
    return root
