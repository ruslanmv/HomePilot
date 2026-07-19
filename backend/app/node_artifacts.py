"""
Node Artifacts — Phase 3 of the OllaBridge Cloud Mirror.

Short-lived, owner-scoped storage for job outputs (generated images, video,
audio). OllaBridge Local relays these to the browser; the cloud never keeps
a permanent copy by default (design §19).

Controls enforced here (design §19, §20.5):
  - short expiration (NODE_ARTIFACT_TTL_SEC, default 1h); expired artifacts
    are swept and unreadable
  - content-type + size caps (NODE_ARTIFACT_MAX_MB, default 64)
  - opaque ids only, strict filename allowlist on the serving route
  - localhost-only serving (the sidecar reads them); no public URLs
  - owner tag stored with each artifact for the cloud's authorization layer

ADDITIVE - self-contained; nothing else imports or depends on it.
"""
from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel

_ALLOWED_CONTENT_TYPES = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
    "video/mp4": ".mp4", "video/webm": ".webm",
    "audio/wav": ".wav", "audio/mpeg": ".mp3",
    "application/json": ".json", "text/plain": ".txt",
}

_ID_RE = re.compile(r"^art_[A-Za-z0-9]{16,40}$")


class ArtifactMeta(BaseModel):
    artifact_id: str
    content_type: str
    filename: str
    size_bytes: int
    owner: str = ""
    created_at: float
    expires_at: float


def _dir() -> Path:
    base = os.getenv("NODE_ARTIFACTS_DIR", "").strip()
    p = Path(base) if base else Path(__file__).resolve().parents[1] / "data" / "node_artifacts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ttl_sec() -> int:
    try:
        return max(60, int(os.getenv("NODE_ARTIFACT_TTL_SEC", "3600")))
    except ValueError:
        return 3600


def _max_bytes() -> int:
    try:
        return max(1, int(os.getenv("NODE_ARTIFACT_MAX_MB", "64"))) * 1024 * 1024
    except ValueError:
        return 64 * 1024 * 1024


def _meta_path(artifact_id: str) -> Path:
    return _dir() / f"{artifact_id}.meta.json"


def store(data: bytes, content_type: str, filename: str = "",
          owner: str = "") -> ArtifactMeta:
    """Persist bytes as a short-lived artifact. Raises on bad type/size."""
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise ValueError(f"content_type not allowed: {content_type}")
    if len(data) > _max_bytes():
        raise ValueError(f"artifact exceeds size cap ({_max_bytes()} bytes)")

    artifact_id = "art_" + uuid.uuid4().hex + uuid.uuid4().hex[:8]
    ext = _ALLOWED_CONTENT_TYPES[content_type]
    now = time.time()
    meta = ArtifactMeta(
        artifact_id=artifact_id, content_type=content_type,
        filename=(filename or f"{artifact_id}{ext}")[:120],
        size_bytes=len(data), owner=owner,
        created_at=now, expires_at=now + _ttl_sec(),
    )
    (_dir() / f"{artifact_id}{ext}").write_bytes(data)
    _meta_path(artifact_id).write_text(meta.model_dump_json(), encoding="utf-8")
    _sweep_expired()
    return meta


def get_meta(artifact_id: str) -> Optional[ArtifactMeta]:
    if not _ID_RE.match(artifact_id):
        return None
    mp = _meta_path(artifact_id)
    if not mp.is_file():
        return None
    try:
        meta = ArtifactMeta.model_validate_json(mp.read_text(encoding="utf-8"))
    except Exception:
        return None
    if time.time() >= meta.expires_at:
        _delete(artifact_id, meta)
        return None
    return meta


def get_path(artifact_id: str) -> Optional[Path]:
    meta = get_meta(artifact_id)
    if not meta:
        return None
    ext = _ALLOWED_CONTENT_TYPES.get(meta.content_type, "")
    path = _dir() / f"{artifact_id}{ext}"
    return path if path.is_file() else None


def _delete(artifact_id: str, meta: Optional[ArtifactMeta] = None) -> None:
    try:
        if meta:
            ext = _ALLOWED_CONTENT_TYPES.get(meta.content_type, "")
            (_dir() / f"{artifact_id}{ext}").unlink(missing_ok=True)
        _meta_path(artifact_id).unlink(missing_ok=True)
    except Exception:
        pass


def _sweep_expired() -> int:
    removed = 0
    now = time.time()
    try:
        for mp in _dir().glob("*.meta.json"):
            try:
                meta = ArtifactMeta.model_validate_json(mp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if now >= meta.expires_at:
                _delete(meta.artifact_id, meta)
                removed += 1
    except Exception:
        pass
    return removed


def allowed_content_types() -> List[str]:
    return sorted(_ALLOWED_CONTENT_TYPES)
