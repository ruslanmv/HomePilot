"""
Where HomePilot's media bytes live.

One interface (``MediaStorage``) for uploads, generated images and videos, avatars and the
other persistent media, keyed by the relative path the registries already store — so every
existing asset resolves unchanged and nothing is moved. ``local`` (the default) is today's
layout under UPLOAD_DIR and needs no service; ``s3`` is any S3-compatible object store
(MEDIA_STORAGE_BACKEND=s3 plus S3_ENDPOINT_URL / S3_BUCKET / credentials). The backend is a
deployment setting, never a caller's decision.

    from .media_storage import get_storage
    get_storage().put("users/<id>/images/<file>.png", data)

Reads go through ``storage_for_read(key)``: the configured backend, else — when that is not
local — this machine's disk, where media from before a switch still is. Design and the phase
plan: docs/design/MEDIA_STORAGE.md.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

from .. import config as _config
from .base import MediaStorage, StorageKeyError, StoredObject, normalize_key
from .local import LocalStorage
from .s3 import S3Settings, S3Storage

__all__ = [
    "MediaStorage", "LocalStorage", "S3Settings", "S3Storage", "StorageKeyError", "StoredObject",
    "AVAILABLE_BACKENDS", "backend_name", "get_storage", "local_storage", "normalize_key",
    "reset_storage", "storage_for_read", "storage_named", "upload_root", "warm_up",
]

DEFAULT_BACKEND = "local"
AVAILABLE_BACKENDS = ("local", "s3")

_lock = threading.Lock()
_current: Optional[MediaStorage] = None
_current_signature: Optional[tuple] = None
_local: Optional[LocalStorage] = None


def upload_root() -> Path:
    """UPLOAD_DIR, or ``backend/data/uploads`` when it is relative — the rule files.py and
    asset_registry.py each carried a copy of. Read at call time, so a repointed
    ``app.config.UPLOAD_DIR`` (tests, DATA_DIR) is honoured."""
    p = Path(_config.UPLOAD_DIR)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[2] / "data" / "uploads"
    return p


def backend_name() -> str:
    return (os.getenv("MEDIA_STORAGE_BACKEND") or DEFAULT_BACKEND).strip().lower() or DEFAULT_BACKEND


def local_storage() -> LocalStorage:
    """This machine's disk under the upload root — the default backend, and where media
    from before a switch to another backend still is."""
    global _local
    root = upload_root()
    with _lock:
        if _local is None or _local.root != root.resolve():
            _local = LocalStorage(root)
        return _local


def get_storage() -> MediaStorage:
    """The configured storage — built once, rebuilt when the backend or its settings change.
    Building it touches no network; the first operation does."""
    global _current, _current_signature
    name = backend_name()
    s3_settings = S3Settings.from_env() if name == "s3" else None
    signature = s3_settings.signature() if s3_settings else (name, str(upload_root()))
    with _lock:
        if _current is None or _current_signature != signature:
            if name == "local":
                _current = LocalStorage(upload_root())
            elif s3_settings is not None:
                _current = S3Storage(s3_settings)
            else:
                raise RuntimeError(
                    f"MEDIA_STORAGE_BACKEND={name!r} is not a backend this HomePilot has: "
                    f"one of {', '.join(AVAILABLE_BACKENDS)}."
                )
            _current_signature = signature
        return _current


def storage_named(name: str) -> Optional[MediaStorage]:
    """The storage called ``name`` as this HomePilot is configured: this disk for 'local', the
    configured backend when that is its name — else None: the bytes are in a store this
    HomePilot is not set up to reach (switched back to local after writing to S3)."""
    name = (name or "local").strip().lower()
    if name == "local":
        return local_storage()
    storage = get_storage()
    return storage if storage.name == name else None


def storage_for_read(key: str) -> MediaStorage:
    """For a key with no registry row (path-based legacy URLs): the configured backend when it
    has the object (or is local), else this machine's disk — so switching to S3 never hides
    the media written before it, and a remote store that is down still leaves the local ones
    readable. Registered assets do not need this: their row names the backend."""
    storage = get_storage()
    if storage.name == "local":
        return storage
    try:
        if storage.exists(key):
            return storage
    except StorageKeyError:
        raise
    except Exception:
        pass  # unreachable or misconfigured: fall through to the disk for this read
    local = local_storage()
    return local if local.exists(key) else storage


def warm_up() -> None:
    """At startup: say which backend is in use and, when it is remote, load its client library
    and reach the bucket on a background thread — so the first upload does not pay for it
    (boto3 took 14 s to load from a venv on a Windows share; the second upload took 0.2 s)."""
    try:
        storage = get_storage()
    except Exception as e:
        print(f"[media-storage] not available: {e}")
        return
    if isinstance(storage, S3Storage):
        s = storage.settings
        print(f"[media-storage] backend=s3 endpoint={s.endpoint_url or 'aws'} bucket={s.bucket}"
              + (f" prefix={s.prefix}" if s.prefix else "") + " (media from before the switch is read from the disk)")
    else:
        print(f"[media-storage] backend={storage.name} root={upload_root()}")
        return

    def _warm() -> None:
        try:
            storage.exists(".warm-up")        # builds the client and makes sure the bucket is there
            print("[media-storage] s3 ready")
        except Exception as e:
            print(f"[media-storage] s3 not reachable yet: {e}")

    threading.Thread(target=_warm, name="media-storage-warm-up", daemon=True).start()


def reset_storage() -> None:
    """Forget the built storages (tests that change UPLOAD_DIR or the backend)."""
    global _current, _current_signature, _local
    with _lock:
        _current = None
        _current_signature = None
        _local = None
