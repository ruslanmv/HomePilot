"""
Avatar Studio — persistent storage helpers.

Saves generated avatars, metadata and thumbnails to disk.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from .config import CFG


def ensure_storage_root() -> Path:
    root = Path(CFG.storage_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def make_public_url(local_path: Path) -> str:
    """Map a local file path to a URL the frontend can fetch."""
    return f"/static/avatars/{local_path.name}"


def copy_into_storage(src_path: Path) -> Path:
    root = ensure_storage_root()
    dst = root / f"{int(time.time())}_{src_path.name}"
    shutil.copy2(src_path, dst)
    return dst
