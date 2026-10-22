"""
The MediaStorage interface: where HomePilot keeps media bytes.

A key is a relative POSIX path under the storage root — the same string that
``file_assets.rel_path`` and ``assets.storage_key`` already hold ("users/<id>/images/<f>.png",
"avatar_<id>_1a2b.png"), so every existing asset resolves unchanged. Which backend serves a
key is a deployment setting (``MEDIA_STORAGE_BACKEND``), never a caller's decision. Phase 1
ships ``local``; another backend is another subclass of this, run through the same contract
tests (backend/tests/test_media_storage.py). Design: docs/design/MEDIA_STORAGE.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, ContextManager, Optional, Union

Bytes = Union[bytes, bytearray, memoryview]


class StorageKeyError(ValueError):
    """A key that would leave the storage root, or names nothing."""


@dataclass(frozen=True)
class StoredObject:
    backend: str
    key: str
    size_bytes: int


def normalize_key(key: str) -> str:
    """The canonical form of a key, or StorageKeyError.

    Backslashes are separators (keys written on Windows), repeated and trailing slashes
    collapse, and nothing may climb out: no absolute paths, drive letters, "..", NUL.
    """
    raw = str(key or "").replace("\\", "/")
    if not raw.strip() or "\x00" in raw:
        raise StorageKeyError("empty key")
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise StorageKeyError(f"an absolute path is not a key: {key!r}")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise StorageKeyError(f"key leaves the storage root: {key!r}")
    return "/".join(parts)


class MediaStorage(ABC):
    """Bytes by key. Writes are atomic: a reader never sees a half-written object."""

    name: str = "abstract"

    @abstractmethod
    def put(self, key: str, data: Union[Bytes, BinaryIO], *, overwrite: bool = True) -> StoredObject:
        """Store bytes (or a readable stream) at ``key``. FileExistsError when it is
        there and ``overwrite`` is False."""

    @abstractmethod
    def open_write(self, key: str, *, overwrite: bool = True) -> ContextManager[BinaryIO]:
        """A writable stream for ``key``, committed when the block ends normally and
        discarded entirely — nothing at ``key``, no leftovers — when it raises."""

    @abstractmethod
    def open(self, key: str) -> BinaryIO:
        """A readable stream; FileNotFoundError when there is no such object."""

    def read(self, key: str) -> bytes:
        with self.open(key) as f:
            return f.read()

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def size(self, key: str) -> int:
        """Size in bytes; FileNotFoundError when there is no such object."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Remove the object. True when something was removed, False when it was not there."""

    @abstractmethod
    def copy(self, src_key: str, dst_key: str, *, overwrite: bool = True) -> StoredObject: ...

    def local_path(self, key: str) -> Optional[Path]:
        """The object's path on this machine's filesystem, when the backend has one (a
        FileResponse can serve it directly); None for remote storage."""
        return None
