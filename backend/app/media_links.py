"""
Signed links to one file — the grant for an <img> tag or a share that is not an account
credential (docs/design/MEDIA_STORAGE.md, audit item A3).

``/files/<asset_id>?exp=<unix seconds>&sig=<hmac>``: valid for that asset until ``exp``,
nothing else. The key is ``MEDIA_SIGNING_KEY`` when set, else one generated once into
``<data dir>/.media_signing_key`` (mode 600) next to the database.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Dict, Optional

from .storage import _get_db_path

DEFAULT_TTL_S = 600
MAX_TTL_S = 7 * 24 * 3600
_key_cache: Optional[bytes] = None


def _key_file() -> Path:
    return Path(_get_db_path()).parent / ".media_signing_key"


def signing_key() -> bytes:
    global _key_cache
    if _key_cache:
        return _key_cache
    env = (os.getenv("MEDIA_SIGNING_KEY") or "").strip()
    if env:
        _key_cache = env.encode("utf-8")
        return _key_cache
    path = _key_file()
    try:
        key = path.read_bytes().strip()
        if key:
            _key_cache = key
            return key
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32).encode("ascii")
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key + b"\n")
    except FileExistsError:
        key = path.read_bytes().strip()
    _key_cache = key
    return key


def reset_key_cache() -> None:
    global _key_cache
    _key_cache = None


def _signature(asset_id: str, exp: int) -> str:
    message = f"{asset_id}|{int(exp)}".encode("utf-8")
    return hmac.new(signing_key(), message, hashlib.sha256).hexdigest()


def sign(asset_id: str, ttl_s: int = DEFAULT_TTL_S, now: Optional[float] = None) -> Dict[str, object]:
    """``{"exp": …, "sig": …, "url": "/files/<id>?exp=…&sig=…"}`` for ``asset_id``."""
    ttl = max(1, min(int(ttl_s or DEFAULT_TTL_S), MAX_TTL_S))
    exp = int((now if now is not None else time.time()) + ttl)
    sig = _signature(asset_id, exp)
    return {"exp": exp, "sig": sig, "url": f"/files/{asset_id}?exp={exp}&sig={sig}"}


def verify(asset_id: str, exp: Optional[str], sig: Optional[str], now: Optional[float] = None) -> bool:
    """True when ``sig`` is this asset's signature for ``exp`` and ``exp`` is still ahead."""
    if not asset_id or not exp or not sig:
        return False
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < (now if now is not None else time.time()):
        return False
    return hmac.compare_digest(_signature(asset_id, exp_i), str(sig).strip())
