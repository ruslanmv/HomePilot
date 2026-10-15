"""Finding meetings in a pile of files — an upload, an archive, or a synced folder.

One discovery routine for all three, so an Insta360 folder looks the same whether it was
zipped and uploaded or picked up from ``D:\\AIRecord``:

* **AIRecord** — a folder holding ``.airecord_data/record_info.json``. The recording beside
  it is the meeting's audio; ``audio_asr_total.json`` is its transcript (often empty); the
  ASR slices are the device's own working copies and are not imported twice.
* **Audio** — any other recording, paired with a transcript that shares its name
  (``call.mp3`` + ``call.srt``).
* **Transcript only** — a text, subtitle or JSON transcript with no audio.

Discovery only describes; it never copies or changes a file. Names are kept exactly — the
Insta360 ``∶`` in ``12∶31∶51`` is a real character and stays one.
"""

from __future__ import annotations

import os
import re
import stat
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from .media import AUDIO_EXTENSIONS
from .parsers import TRANSCRIPT_EXTENSIONS

_IGNORED_NAMES = {"dot.txt", "desktop.ini", "thumbs.db", ".ds_store"}
_TEMP_SUFFIXES = (".tmp", ".part", ".crdownload", ".partial", ".download", ".lock")

#: Limits for an uploaded archive. Generous for real meetings, tight enough that an archive
#: built to expand without end is refused before it fills the disk.
ZIP_MAX_ENTRIES = 5000
ZIP_MAX_RATIO = 200
ZIP_MAX_DEPTH = 12


@dataclass
class FileRef:
    rel: str            # path relative to the scan root, POSIX separators
    path: Path          # absolute path on disk
    size: int
    mtime: float
    role: str           # audio | transcript | metadata | slice

    def as_dict(self) -> Dict[str, Any]:
        return {"rel": self.rel, "name": PurePosixPath(self.rel).name, "size": self.size,
                "mtime": self.mtime, "role": self.role}


@dataclass
class Candidate:
    key: str
    kind: str                         # airecord | audio | transcript
    title: str
    started_at: Optional[float]
    ended_at: Optional[float] = None
    claimed_duration_ms: Optional[int] = None
    audio: Optional[FileRef] = None
    transcript: Optional[FileRef] = None
    metadata_files: List[FileRef] = field(default_factory=list)
    ignored: List[FileRef] = field(default_factory=list)
    origin: Optional[Tuple[str, str]] = None   # ("airecord", localMeetingId)
    raw_metadata: Dict[str, Any] = field(default_factory=dict)
    time_source: str = "metadata"     # metadata | filename | file_date
    warnings: List[str] = field(default_factory=list)

    @property
    def files(self) -> List[FileRef]:
        out = [f for f in (self.audio, self.transcript) if f is not None]
        return out + list(self.metadata_files)


def _skip(name: str) -> bool:
    lower = name.lower()
    return (
        lower in _IGNORED_NAMES
        or lower.endswith(_TEMP_SUFFIXES)
        or name.startswith("~$")
        or name.startswith("._")
    )


def _ref(root: Path, path: Path, role: str) -> FileRef:
    st = path.stat()
    return FileRef(rel=path.relative_to(root).as_posix(), path=path, size=st.st_size,
                   mtime=st.st_mtime, role=role)


# 2026_10_10 12∶31∶51 · 2026-10-10 12-31-51 · 20261010_123151 · 2026-10-10T12:31:51
_NAME_TIME = re.compile(
    r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})[ T_-]+(\d{2})[:∶꞉\-_.]?(\d{2})[:∶꞉\-_.]?(\d{2})"
)


def time_from_name(name: str) -> Optional[datetime]:
    m = _NAME_TIME.search(unicodedata.normalize("NFKC", name))
    if not m:
        return None
    try:
        return datetime(*(int(g) for g in m.groups()))
    except ValueError:
        return None


def display_title(name: str, *, fallback_prefix: str = "Imported meeting") -> str:
    """A person-readable title. A name that is only a timestamp becomes "… · Oct 10, 12:31";
    "Design Review 2026-02-10 13-00-00" becomes "Design Review" (the time is kept as the
    meeting's start, so it still shows on the card)."""
    stem = name.strip()
    when = time_from_name(stem)
    if not when:
        return stem
    normalized = unicodedata.normalize("NFKC", stem)
    leftover = re.sub(r"\s{2,}", " ", _NAME_TIME.sub(" ", normalized)).strip(" -_.·()[]")
    if not leftover:
        return f"{fallback_prefix} · {when.strftime('%b')} {when.day}, {when.strftime('%H:%M')}"
    return leftover


def _airecord_candidate(root: Path, folder: Path) -> Candidate:
    import json  # noqa: PLC0415

    data_dir = folder / ".airecord_data"
    info_path = data_dir / "record_info.json"
    info: Dict[str, Any] = {}
    warnings: List[str] = []
    try:
        info = json.loads(info_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        warnings.append("record_info.json could not be read; times come from the folder name.")
    name = str(info.get("meetingname") or folder.name)
    started = info.get("startTime")
    ended = info.get("endTime")
    started_at = float(started) if isinstance(started, (int, float)) and started > 0 else None
    ended_at = float(ended) if isinstance(ended, (int, float)) and ended > 0 else None
    time_source = "metadata"
    if started_at is None:
        when = time_from_name(name) or time_from_name(folder.name)
        if when:
            started_at, time_source = when.timestamp(), "filename"
    claimed = info.get("duration")
    claimed_ms = int(claimed) if isinstance(claimed, (int, float)) and claimed > 0 else None

    audio_files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
                   and not _skip(p.name)]
    # The recording that carries the meeting's own name, else the largest.
    audio_files.sort(key=lambda p: (p.stem != name and p.stem != folder.name, -p.stat().st_size))
    cand = Candidate(
        key=folder.relative_to(root).as_posix() or ".",
        kind="airecord",
        title=display_title(name),
        started_at=started_at,
        ended_at=ended_at,
        claimed_duration_ms=claimed_ms,
        audio=_ref(root, audio_files[0], "audio") if audio_files else None,
        raw_metadata={"record_info": info},
        time_source=time_source,
        warnings=warnings,
    )
    local_id = str(info.get("localMeetingId") or "").strip()
    if local_id and local_id.lower() != "none":
        cand.origin = ("airecord", local_id)
    for extra in audio_files[1:]:
        cand.ignored.append(_ref(root, extra, "audio"))
    if info_path.is_file():
        cand.metadata_files.append(_ref(root, info_path, "metadata"))
    asr = data_dir / "audio_asr_total.json"
    if asr.is_file():
        cand.transcript = _ref(root, asr, "transcript")
    slices = data_dir / "asr_audio_slice"
    if slices.is_dir():
        for p in sorted(slices.iterdir()):
            if p.is_file():
                cand.ignored.append(_ref(root, p, "slice"))
    if not cand.audio:
        cand.warnings.append("No recording was found in this AIRecord folder.")
    description = str(info.get("description") or "").strip()
    if description and description != "xxxx会议描述":  # the device's placeholder text
        cand.raw_metadata["description"] = description
    return cand


def _file_time(path: Path, name: str) -> Tuple[Optional[float], str]:
    when = time_from_name(name)
    if when:
        return when.timestamp(), "filename"
    try:
        return path.stat().st_mtime, "file_date"
    except OSError:
        return None, "file_date"


def discover(root: Path, *, max_files: int = 20000, max_depth: int = 6) -> List[Candidate]:
    """Every meeting found below ``root``, oldest first. Never follows symlinks."""
    root = root.resolve()
    candidates: List[Candidate] = []
    airecord_dirs: List[Path] = []
    loose_audio: Dict[str, Path] = {}
    loose_text: Dict[str, Path] = {}
    seen = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        depth = len(current.relative_to(root).parts)
        if depth > max_depth:
            dirnames[:] = []
            continue
        if (current / ".airecord_data" / "record_info.json").is_file():
            airecord_dirs.append(current)
            dirnames[:] = []  # its contents belong to the recording
            continue
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "__MACOSX")
        for fname in sorted(filenames):
            seen += 1
            if seen > max_files:
                break
            if fname.startswith(".") or _skip(fname):
                continue
            path = current / fname
            try:
                if path.is_symlink() or not path.is_file():
                    continue
            except OSError:
                continue
            ext = path.suffix.lower()
            key = (current / path.stem).relative_to(root).as_posix()
            if ext in AUDIO_EXTENSIONS:
                loose_audio[key] = path
            elif ext in TRANSCRIPT_EXTENSIONS:
                loose_text.setdefault(key, path)

    for folder in airecord_dirs:
        candidates.append(_airecord_candidate(root, folder))

    for key, path in loose_audio.items():
        started_at, source = _file_time(path, path.name)
        cand = Candidate(key=key, kind="audio", title=display_title(path.stem, fallback_prefix="Recording"),
                         started_at=started_at, audio=_ref(root, path, "audio"), time_source=source)
        if source == "file_date":
            cand.warnings.append("The start time comes from the file's date; check it.")
        text = loose_text.pop(key, None)
        if text is not None:
            cand.transcript = _ref(root, text, "transcript")
        candidates.append(cand)

    for key, path in loose_text.items():
        started_at, source = _file_time(path, path.name)
        candidates.append(Candidate(key=key, kind="transcript",
                                    title=display_title(path.stem, fallback_prefix="Transcript"),
                                    started_at=started_at, transcript=_ref(root, path, "transcript"),
                                    time_source=source))

    candidates.sort(key=lambda c: (c.started_at or 0, c.key))
    return candidates


# ── archives ────────────────────────────────────────────────────────────────


class UnsafeArchive(ValueError):
    pass


def _safe_member(name: str) -> Optional[str]:
    """The member's relative path, normalised — or None for anything that escapes."""
    name = unicodedata.normalize("NFC", name.replace("\\", "/"))
    if not name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or len(parts) > ZIP_MAX_DEPTH:
        return None
    return "/".join(parts)


def extract_zip(archive: Path, dest: Path, *, max_total_bytes: int) -> List[str]:
    """Extract an upload safely: no path escapes, no symlinks, no zip bombs.

    Returns the relative paths written. Raises :class:`UnsafeArchive` with a reason a person
    can act on; nothing is left half-extracted to be mistaken for an import.
    """
    written: List[str] = []
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise UnsafeArchive("This is not a ZIP archive HomePilot can open.") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > ZIP_MAX_ENTRIES:
            raise UnsafeArchive(f"The archive has more than {ZIP_MAX_ENTRIES} files.")
        total = sum(i.file_size for i in infos)
        if total > max_total_bytes:
            raise UnsafeArchive("The archive expands to more than the import size limit.")
        dest.mkdir(parents=True, exist_ok=True)
        for info in infos:
            rel = _safe_member(info.filename)
            if rel is None:
                raise UnsafeArchive(f"Refused an unsafe path in the archive: “{info.filename}”")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                continue  # a link inside an upload points somewhere the user did not upload
            if info.is_dir():
                (dest / rel).mkdir(parents=True, exist_ok=True)
                continue
            if info.compress_size and info.file_size > 10 * 1024 * 1024 and \
                    info.file_size / max(1, info.compress_size) > ZIP_MAX_RATIO:
                raise UnsafeArchive("The archive is compressed suspiciously well (a possible zip bomb).")
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            written_bytes = 0
            with zf.open(info) as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    written_bytes += len(chunk)
                    if written_bytes > info.file_size + 1024:
                        raise UnsafeArchive("An archive member is larger than it claims.")
                    out.write(chunk)
            # Keep the recorder's own timestamp — it is what "newest" sorts by.
            try:
                ts = time.mktime(info.date_time + (0, 0, -1))
                os.utime(target, (ts, ts))
            except (OverflowError, ValueError, OSError):
                pass
            written.append(rel)
    return written
