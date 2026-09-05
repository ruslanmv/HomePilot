"""Deleting a meeting, and what each retention mode keeps (batch MS14).

Two things happen when a meeting is deleted: rows go, and files go. The rows are the store's
job; the files are this module's, because the store deliberately does not know where the upload
directory is and should not learn.

**Retention decides what was ever kept, not what deletion removes.** Deleting a meeting removes
everything belonging to it whatever the mode — a user who presses delete means delete. What the
mode governs is which files existed to be removed in the first place:

===============  ====================================================
``text``         transcript only. No frame was ever written to disk.
``text+frames``  transcript and slide images.
``all``          transcript, slide images and the audio.
===============  ====================================================

**A file is only removed if the meeting owned it.** A keyframe URL arrives from a client, and a
client can say anything. Every path is resolved under the upload root and checked to be inside
it before anything is unlinked, so a crafted `../../` URL deletes nothing. That check is the
reason this is a module rather than three lines in the route.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import store

log = logging.getLogger(__name__)

#: URLs the recorder produces are served from here. Anything else is not ours to delete.
FILES_PREFIX = "/files/"


def upload_root() -> Optional[Path]:
    """Where uploaded files live, or ``None`` when that cannot be determined.

    Imported lazily and guarded: this module is meant to be importable — and testable — without
    the FastAPI app, the same way ``store`` reaches for ``storage``.
    """
    try:
        from ..files import _upload_root

        return Path(_upload_root())
    except Exception:  # noqa: BLE001
        log.debug("meetingsense: no upload root available", exc_info=True)
        return None


def resolve_owned(url: str, root: Path) -> Optional[Path]:
    """The on-disk path for a ``/files/…`` URL, if and only if it sits under ``root``.

    Returns ``None`` for anything else — an absolute URL, a path with ``..`` in it, a symlink
    pointing outside. The keyframe URL came from a client at some point, and a delete endpoint
    that unlinks whatever it is handed is a delete endpoint that can be pointed at anything.
    """
    if not url or not isinstance(url, str) or not url.startswith(FILES_PREFIX):
        return None
    relative = url[len(FILES_PREFIX):].split("?")[0].split("#")[0]
    if not relative or relative.startswith("/"):
        return None
    try:
        candidate = (root / relative).resolve()
        base = root.resolve()
    except (OSError, RuntimeError):
        return None
    # `is_relative_to` rather than a string prefix: "/files/../etc" and a symlink out both
    # resolve to somewhere outside the root, and a prefix check would miss the second.
    if not candidate.is_relative_to(base):
        return None
    return candidate


def remove_files(urls: Iterable[str]) -> Dict[str, int]:
    """Unlink the files a meeting owns. Never raises.

    Counts rather than a boolean, so the endpoint can report what actually happened: a user who
    deletes a meeting with twelve slides and is told "done" has no way to know whether the
    twelve images went with it.
    """
    root = upload_root()
    counts = {"removed": 0, "missing": 0, "refused": 0}
    if root is None:
        counts["refused"] = len(list(urls))
        return counts

    for url in urls:
        target = resolve_owned(url, root)
        if target is None:
            counts["refused"] += 1
            continue
        try:
            if target.is_file():
                target.unlink()
                counts["removed"] += 1
            else:
                counts["missing"] += 1
        except OSError:
            log.warning("meetingsense: could not remove %s", url)
            counts["missing"] += 1
    return counts


def keeps_frames(retention: str) -> bool:
    """Whether this mode ever wrote a slide image to disk."""
    return retention in ("text+frames", "all")


def keeps_audio(retention: str) -> bool:
    """Whether this mode ever kept the audio. Nothing writes audio yet; the answer is here so
    the delete path is already right when something does."""
    return retention == "all"


def delete_meeting(meeting_id: str) -> Optional[Dict[str, Any]]:
    """Remove a meeting: its rows, and the files it owned. ``None`` if there was no meeting.

    Deliberately *not* dependent on the retention mode. Whatever was kept is removed — a user
    who presses delete means delete, and a mode that let something survive it would be a
    setting that quietly overrode an instruction.
    """
    meeting = store.get_meeting(meeting_id)
    if meeting is None:
        return None

    # Read the keyframes before the rows go, or there is nothing left to say which files were
    # this meeting's.
    urls = [k.get("url") for k in store.get_keyframes(meeting_id) if k.get("url")]
    files = remove_files(urls)
    # MS15's third store. A meeting deleted from SQLite but left in the vector index is a
    # meeting that still answers questions after the user deleted it — the worst available
    # reading of "delete", and the one nobody would notice until a persona quoted it back.
    from . import retrieval

    indexed = retrieval.forget_meeting(meeting_id)
    rows = store.delete_meeting(meeting_id)
    return {
        "meeting_id": meeting_id,
        "retention": meeting.get("retention"),
        "rows": rows,
        "files": files,
        # Reported rather than assumed: `False` means there was no vector store to clean, which
        # on an install without Chroma is the correct and complete answer.
        "index_cleared": indexed,
    }
