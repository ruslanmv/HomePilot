"""Captured frames, and the sweep that removes them (batch RS1).

A remote screenshot is the most sensitive file HomePilot writes and the least worth keeping.
So a frame here has a lifetime measured from the moment it was taken, and both ends enforce
it: :func:`get` refuses an expired frame whether or not the sweep has run, and :func:`sweep`
deletes by file age so a restart — which loses the in-memory index — still cleans up.

Deleting by age off the filesystem rather than off the index is the whole reason this is not
a dictionary. The index is a cache of what the process happens to remember; the directory is
the truth, and the truth is what has to end up empty.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import config


@dataclass(frozen=True)
class Frame:
    """One still. ``frame_id`` is the only thing that ever leaves this machine as a name."""

    frame_id: str
    path: Path
    created: float
    width: int
    height: int
    size: int
    mechanism: str  # 'share' (a granted tab) | 'desktop' (headless)

    def age(self, now: Optional[float] = None) -> float:
        return max(0.0, (now if now is not None else time.time()) - self.created)

    def expired(self, now: Optional[float] = None) -> bool:
        return self.age(now) > config.frame_ttl_s()

    def handle(self, now: Optional[float] = None) -> Dict[str, object]:
        """The shape the client keeps. Deliberately small — no path, no absolute URL.

        ``expires_in`` rather than an expiry timestamp: the client's clock is not this
        machine's clock, and a countdown survives the difference.
        """
        return {
            "frame_id": self.frame_id,
            "url": f"/v1/screensense/frame/{self.frame_id}",
            "width": self.width,
            "height": self.height,
            "bytes": self.size,
            "captured_at": self.created,
            "age_s": round(self.age(now), 3),
            "expires_in_s": round(max(0.0, config.frame_ttl_s() - self.age(now)), 3),
            "mechanism": self.mechanism,
            "device": config.device_name(),
        }


_lock = threading.Lock()
_index: Dict[str, Frame] = {}


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """Width and height off the JPEG's own SOF marker, with no image library.

    Pillow is not a dependency of this package and importing it to read two integers would
    make the whole feature fail on a machine that lacks it. A frame whose dimensions cannot
    be read is still a perfectly good frame, so this returns ``(0, 0)`` rather than raising —
    the card falls back to the image's natural size, which the browser knows anyway.
    """
    try:
        i, end = 2, len(data)
        while i + 9 < end:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            # SOF0..SOF15, minus the four that are not frame headers.
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height = int.from_bytes(data[i + 5 : i + 7], "big")
                width = int.from_bytes(data[i + 7 : i + 9], "big")
                return width, height
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            segment = int.from_bytes(data[i + 2 : i + 4], "big")
            if segment < 2:
                break
            i += 2 + segment
    except Exception:
        pass
    return 0, 0


def store(data: bytes, mechanism: str) -> Frame:
    """Write one frame and return its handle. Sweeps first, so the directory stays bounded."""
    sweep()
    frame_id = uuid.uuid4().hex
    width, height = _jpeg_size(data)
    path = config.frames_dir() / f"{frame_id}.jpg"
    # Written to a temporary name and renamed, the same way ``/upload`` does it: a reader
    # that arrives mid-write must find nothing rather than half a picture.
    tmp = path.with_suffix(".jpg.tmp")
    tmp.write_bytes(data)
    tmp.rename(path)
    frame = Frame(
        frame_id=frame_id,
        path=path,
        created=time.time(),
        width=width,
        height=height,
        size=len(data),
        mechanism=mechanism,
    )
    with _lock:
        _index[frame_id] = frame
    return frame


def get(frame_id: str) -> Optional[Frame]:
    """The frame, or ``None`` if it never existed, has expired, or is gone from disk.

    All three collapse to one answer on purpose. A caller that could tell "expired" from
    "never existed" could ask this endpoint whether a given id was ever issued.
    """
    key = str(frame_id or "").strip()
    if not key or not key.isalnum():
        return None
    with _lock:
        frame = _index.get(key)
    if frame is None:
        return None
    if frame.expired():
        drop(key)
        return None
    if not frame.path.exists():
        drop(key)
        return None
    return frame


def drop(frame_id: str) -> bool:
    """Forget one frame and unlink it. True if there was something to forget."""
    with _lock:
        frame = _index.pop(str(frame_id or ""), None)
    if frame is None:
        return False
    try:
        frame.path.unlink(missing_ok=True)
    except OSError:
        pass
    return True


def sweep(now: Optional[float] = None) -> int:
    """Delete every frame older than the TTL, from the index *and* from disk.

    The directory walk is the part that matters. The index is empty after a restart, and the
    files are not — without this, a crash would leave somebody's desktop on disk forever.
    """
    when = now if now is not None else time.time()
    ttl = config.frame_ttl_s()
    removed = 0

    with _lock:
        stale: List[str] = [k for k, f in _index.items() if (when - f.created) > ttl]
        for key in stale:
            frame = _index.pop(key, None)
            if frame is not None:
                try:
                    frame.path.unlink(missing_ok=True)
                except OSError:
                    pass
                removed += 1

    try:
        for path in config.frames_dir().glob("*.jpg*"):
            try:
                if (when - path.stat().st_mtime) > ttl:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
    except OSError:
        pass
    return removed


def reset() -> None:
    """Forget everything, for tests. Files are unlinked; the directory stays."""
    with _lock:
        keys = list(_index)
    for key in keys:
        drop(key)
