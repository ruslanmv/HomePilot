"""
Per-user media quota (docs/design/MEDIA_STORAGE.md, Phase 4).

Off by default: ``MEDIA_QUOTA_MB_PER_USER=0`` (unlimited) keeps a local HomePilot exactly as
it was. With a limit, an upload that would take a user past it is refused with 413 before any
bytes are stored; files in the trash no longer count.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Dict

from fastapi import HTTPException

from .storage import _get_db_path, ensure_file_assets_columns


def quota_bytes() -> int:
    """The per-user limit in bytes, 0 for none. Read at call time so a restart is not needed."""
    raw = (os.getenv("MEDIA_QUOTA_MB_PER_USER") or "0").strip()
    try:
        mb = float(raw)
    except ValueError:
        mb = 0.0
    return int(mb * 1024 * 1024) if mb > 0 else 0


def usage_bytes(user_id: str) -> int:
    if not user_id:
        return 0
    con = sqlite3.connect(_get_db_path())
    try:
        ensure_file_assets_columns(con)
        row = con.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM file_assets WHERE user_id = ? AND deleted_at IS NULL",
            (user_id,),
        ).fetchone()
        return int(row[0] or 0)
    finally:
        con.close()


def usage(user_id: str) -> Dict[str, int]:
    return {"used_bytes": usage_bytes(user_id), "quota_bytes": quota_bytes()}


def check(user_id: str, add_bytes: int) -> None:
    """Raise 413 when storing ``add_bytes`` more would take ``user_id`` past the quota."""
    limit = quota_bytes()
    if not limit or not user_id:
        return
    used = usage_bytes(user_id)
    if used + max(0, int(add_bytes or 0)) > limit:
        mb = 1024 * 1024
        raise HTTPException(
            status_code=413,
            detail=f"Storage quota reached: {used / mb:.0f} of {limit / mb:.0f} MB used. "
                   "Delete some files, or ask the operator to raise MEDIA_QUOTA_MB_PER_USER.",
        )
