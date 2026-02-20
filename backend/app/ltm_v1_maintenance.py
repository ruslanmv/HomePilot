"""
LTM V1 Maintenance — scheduled cleanup routines for enterprise personas.

Runs TTL expiry, per-category cap enforcement, and orphan cleanup.
Designed to be called from:
  1. POST /persona/memory/maintenance (manual trigger)
  2. Lazy background (future cron/job runner)

All operations are safe, idempotent, and non-destructive to core data
(only removes entries that violate TTL or exceed caps).

IMPORTANT: Column compatibility with Memory V2.
  - last_access_at is REAL (unix timestamp) — shared with V2.
  - access_count is INTEGER — shared with V2.
  - is_pinned and expires_at are V1-specific additive columns.
  - ensure_v1_hardening_columns() uses PRAGMA skip-if-exists pattern.

Golden rule: ADDITIVE ONLY.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from .storage import _get_db_path
from .ltm_v1_policy import (
    TTL_MAP,
    DEFAULT_TTL,
    CAP_MAP,
    DEFAULT_CAP,
    TOTAL_CAP,
    get_ttl,
    get_cap,
)


# ---------------------------------------------------------------------------
# Schema extension (additive ALTER TABLE — safe to run repeatedly)
# ---------------------------------------------------------------------------

def ensure_v1_hardening_columns() -> None:
    """
    Add V1-hardening-specific columns to persona_memory.
    Safe to call on every startup — skips columns that already exist.

    Note: last_access_at and access_count are already added by memory_v2.py.
    We only add is_pinned and expires_at here.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("PRAGMA table_info(persona_memory)")
    existing = {row[1] for row in cur.fetchall()}

    additions = [
        ("is_pinned",  "INTEGER DEFAULT 0"),       # 1 = user-pinned, skip TTL/cap eviction
        ("expires_at", "REAL DEFAULT 0"),           # Unix timestamp; 0 = "never expires"
    ]

    for col_name, col_def in additions:
        if col_name not in existing:
            cur.execute(f"ALTER TABLE persona_memory ADD COLUMN {col_name} {col_def}")

    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------

def expire_by_ttl(project_id: str) -> int:
    """
    Delete memories that have exceeded their category TTL.
    Skips pinned entries (is_pinned=1) and entries with expires_at=0 (no expiry).

    Uses updated_at (ISO datetime) as the baseline for TTL calculation,
    falling back to created_at if updated_at is missing.

    Returns count of expired entries.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute(
        """
        SELECT id, category, updated_at, created_at, is_pinned, expires_at
        FROM persona_memory
        WHERE project_id = ?
        """,
        (project_id,),
    )
    rows = cur.fetchall()
    now = time.time()
    deleted = 0

    for row in rows:
        # Skip pinned entries
        if row["is_pinned"]:
            continue

        # If explicit expires_at is set and in the future, skip
        expires_at = float(row["expires_at"] or 0)
        if expires_at > 0 and now < expires_at:
            continue

        # If explicit expires_at is set and in the past, delete
        if expires_at > 0 and now >= expires_at:
            cur.execute("DELETE FROM persona_memory WHERE id = ?", (row["id"],))
            deleted += 1
            continue

        # Otherwise, use category TTL
        cat = row["category"] or "fact"
        ttl = get_ttl(cat)
        if ttl == 0:
            continue  # Category never expires

        # Parse updated_at or created_at (ISO format from V1)
        ts_str = row["updated_at"] or row["created_at"]
        if not ts_str:
            continue

        try:
            # V1 stores timestamps as ISO: "YYYY-MM-DD HH:MM:SS"
            ts = time.mktime(time.strptime(str(ts_str), "%Y-%m-%d %H:%M:%S"))
        except (ValueError, TypeError):
            continue

        if now - ts > ttl:
            cur.execute("DELETE FROM persona_memory WHERE id = ?", (row["id"],))
            deleted += 1

    con.commit()
    con.close()
    return deleted


# ---------------------------------------------------------------------------
# Per-category cap enforcement
# ---------------------------------------------------------------------------

def enforce_category_caps(project_id: str) -> int:
    """
    For each category, if count > cap, delete oldest entries (by updated_at).
    Pinned entries are exempt from eviction.

    Returns count of evicted entries.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Get category counts
    cur.execute(
        """
        SELECT category, COUNT(*) as cnt
        FROM persona_memory
        WHERE project_id = ?
        GROUP BY category
        """,
        (project_id,),
    )
    cat_counts = {row["category"]: row["cnt"] for row in cur.fetchall()}

    evicted = 0
    for cat, count in cat_counts.items():
        cap = get_cap(cat)
        if cap == 0 or count <= cap:
            continue

        overflow = count - cap
        # Delete oldest non-pinned entries that exceed cap
        cur.execute(
            """
            SELECT id FROM persona_memory
            WHERE project_id = ? AND category = ? AND COALESCE(is_pinned, 0) = 0
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (project_id, cat, overflow),
        )
        ids_to_delete = [row["id"] for row in cur.fetchall()]
        for mem_id in ids_to_delete:
            cur.execute("DELETE FROM persona_memory WHERE id = ?", (mem_id,))
            evicted += 1

    con.commit()
    con.close()
    return evicted


# ---------------------------------------------------------------------------
# Total cap enforcement
# ---------------------------------------------------------------------------

def enforce_total_cap(project_id: str) -> int:
    """
    If total entries > TOTAL_CAP, delete oldest non-pinned entries.
    Returns count of evicted entries.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute(
        "SELECT COUNT(*) as cnt FROM persona_memory WHERE project_id = ?",
        (project_id,),
    )
    total = cur.fetchone()["cnt"]

    if total <= TOTAL_CAP:
        con.close()
        return 0

    overflow = total - TOTAL_CAP
    cur.execute(
        """
        SELECT id FROM persona_memory
        WHERE project_id = ? AND COALESCE(is_pinned, 0) = 0
        ORDER BY updated_at ASC
        LIMIT ?
        """,
        (project_id, overflow),
    )
    ids_to_delete = [row["id"] for row in cur.fetchall()]
    evicted = 0
    for mem_id in ids_to_delete:
        cur.execute("DELETE FROM persona_memory WHERE id = ?", (mem_id,))
        evicted += 1

    con.commit()
    con.close()
    return evicted


# ---------------------------------------------------------------------------
# Full maintenance pass
# ---------------------------------------------------------------------------

def run_maintenance(project_id: str) -> Dict[str, Any]:
    """
    Run all maintenance routines for a persona:
      1. TTL expiry
      2. Per-category cap enforcement
      3. Total cap enforcement

    Returns a summary dict.
    """
    expired = expire_by_ttl(project_id)
    cat_evicted = enforce_category_caps(project_id)
    total_evicted = enforce_total_cap(project_id)

    return {
        "project_id": project_id,
        "expired_by_ttl": expired,
        "evicted_by_category_cap": cat_evicted,
        "evicted_by_total_cap": total_evicted,
        "total_cleaned": expired + cat_evicted + total_evicted,
    }


# ---------------------------------------------------------------------------
# Stats for the maintenance endpoint
# ---------------------------------------------------------------------------

def get_memory_stats(project_id: str) -> Dict[str, Any]:
    """
    Return current memory usage stats for a persona.
    Useful for the UI or admin monitoring.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute(
        "SELECT COUNT(*) as cnt FROM persona_memory WHERE project_id = ?",
        (project_id,),
    )
    total = cur.fetchone()["cnt"]

    cur.execute(
        """
        SELECT category, COUNT(*) as cnt
        FROM persona_memory
        WHERE project_id = ?
        GROUP BY category
        """,
        (project_id,),
    )
    by_category = {row["category"]: row["cnt"] for row in cur.fetchall()}

    cur.execute(
        """
        SELECT COUNT(*) as cnt
        FROM persona_memory
        WHERE project_id = ? AND COALESCE(is_pinned, 0) = 1
        """,
        (project_id,),
    )
    pinned_count = cur.fetchone()["cnt"]

    con.close()

    return {
        "project_id": project_id,
        "total": total,
        "total_cap": TOTAL_CAP,
        "by_category": by_category,
        "category_caps": {cat: get_cap(cat) for cat in by_category},
        "pinned_count": pinned_count,
    }
