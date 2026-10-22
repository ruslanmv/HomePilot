"""
LocalStorage — today's layout under UPLOAD_DIR, behind the MediaStorage interface.

Nothing moves: a key is the path relative to the root that the registries already store.
What is new is the discipline — every write lands atomically (temp file in the same
directory, then ``os.replace``), and no key can reach outside the root.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, Union

from .base import Bytes, MediaStorage, StorageKeyError, StoredObject, normalize_key

_COPY_CHUNK = 1024 * 1024


class LocalStorage(MediaStorage):
    name = "local"

    def __init__(self, root: Union[str, Path]) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = self.root / normalize_key(key)
        resolved = path.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise StorageKeyError(f"key leaves the storage root: {key!r}")
        return path

    # ── writing ────────────────────────────────────────────────────────────────

    @contextmanager
    def open_write(self, key: str, *, overwrite: bool = True) -> Iterator[BinaryIO]:
        path = self._path(key)
        if not overwrite and path.exists():
            raise FileExistsError(normalize_key(key))
        path.parent.mkdir(parents=True, exist_ok=True)
        # Same directory as the target, so the final rename is atomic on every filesystem.
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=str(path.parent))
        tmp = Path(tmp_name)
        handle = os.fdopen(fd, "wb")
        try:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.replace(tmp, path)
        except BaseException:
            try:
                handle.close()
            except Exception:
                pass
            tmp.unlink(missing_ok=True)
            raise

    def put(self, key: str, data: Union[Bytes, BinaryIO], *, overwrite: bool = True) -> StoredObject:
        with self.open_write(key, overwrite=overwrite) as out:
            if hasattr(data, "read"):
                shutil.copyfileobj(data, out, _COPY_CHUNK)  # type: ignore[arg-type]
            else:
                out.write(data)  # type: ignore[arg-type]
        return StoredObject(self.name, normalize_key(key), self._path(key).stat().st_size)

    def copy(self, src_key: str, dst_key: str, *, overwrite: bool = True) -> StoredObject:
        with self.open(src_key) as src:
            return self.put(dst_key, src, overwrite=overwrite)

    # ── reading ────────────────────────────────────────────────────────────────

    def open(self, key: str) -> BinaryIO:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(normalize_key(key))
        return path.open("rb")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(normalize_key(key))
        return path.stat().st_size

    def local_path(self, key: str) -> Path:
        return self._path(key)

    # ── removing ───────────────────────────────────────────────────────────────

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.is_file():
            return False
        path.unlink()
        # Empty folders the object leaves behind go too — never the root itself.
        parent = path.parent
        while parent != self.root and self.root in parent.parents:
            try:
                if any(parent.iterdir()):
                    break
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        return True
