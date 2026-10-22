"""A small durable store for the Expert service (SQLite, one file).

What must survive a restart: the capability facts learned about models ("this gateway model
rejects the tools field"), and Deep research jobs with their event history, so a report is
not lost and a client can reconnect. Opened per call with a process lock; a handful of rows
per day, so there is nothing to tune.

Location: ``EXPERT_STATE_DB``, else ``<DATA_DIR>/expert_state.sqlite`` (HomePilot's data
directory), else ``backend/data/expert_state.sqlite`` next to the main database.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import EXPERT_STATE_DB

logger = logging.getLogger("expert.state")

_LOCK = threading.RLock()
_PATH: Optional[Path] = None
_READY = False


def _default_path() -> Path:
    if EXPERT_STATE_DB:
        return Path(EXPERT_STATE_DB)
    data_dir = (os.getenv("DATA_DIR") or "").strip()
    if data_dir:
        return Path(data_dir) / "expert_state.sqlite"
    repo = Path(__file__).resolve().parents[4]
    return repo / "backend" / "data" / "expert_state.sqlite"


def configure(path: Optional[os.PathLike] = None) -> Path:
    """Point the store at ``path`` (tests), or at the default. Creates the schema."""
    global _PATH, _READY
    with _LOCK:
        _PATH = Path(path) if path is not None else _default_path()
        _READY = False
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            _init()
        except Exception as exc:  # noqa: BLE001
            fallback = Path(tempfile.gettempdir()) / "homepilot-expert-state.sqlite"
            logger.warning("expert state store at %s unusable (%s); using %s", _PATH, exc, fallback)
            _PATH = fallback
            _init()
        return _PATH


def path() -> Path:
    if _PATH is None:
        configure()
    return _PATH  # type: ignore[return-value]


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(path()), timeout=10, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _init() -> None:
    global _READY
    with sqlite3.connect(str(_PATH), timeout=10) as con:
        con.execute("CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL, expires REAL)")
        con.execute(
            "CREATE TABLE IF NOT EXISTS deep_jobs(id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL, "
            "status TEXT NOT NULL, snapshot TEXT NOT NULL)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS deep_events(job_id TEXT NOT NULL, seq INTEGER NOT NULL, event TEXT NOT NULL, "
            "PRIMARY KEY(job_id, seq))"
        )
    _READY = True


def _ensure() -> None:
    if not _READY:
        configure(_PATH)


# ── key/value with expiry ────────────────────────────────────────────────────

def kv_get(key: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        _ensure()
        try:
            with _connect() as con:
                row = con.execute("SELECT value, expires FROM kv WHERE key = ?", (key,)).fetchone()
        except sqlite3.Error as exc:
            logger.debug("kv_get %s failed: %s", key, exc)
            return None
    if not row:
        return None
    value, expires = row
    if expires is not None and expires < time.time():
        kv_delete(key)
        return None
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def kv_set(key: str, value: Dict[str, Any], ttl_s: Optional[float] = None) -> None:
    expires = time.time() + ttl_s if ttl_s else None
    with _LOCK:
        _ensure()
        try:
            with _connect() as con:
                con.execute("INSERT OR REPLACE INTO kv(key, value, expires) VALUES (?, ?, ?)",
                            (key, json.dumps(value, ensure_ascii=False), expires))
        except sqlite3.Error as exc:
            logger.debug("kv_set %s failed: %s", key, exc)


def kv_delete(key: str) -> None:
    with _LOCK:
        _ensure()
        try:
            with _connect() as con:
                con.execute("DELETE FROM kv WHERE key = ?", (key,))
        except sqlite3.Error:
            pass


# ── Deep research jobs ───────────────────────────────────────────────────────

def job_save(job_id: str, status: str, snapshot: Dict[str, Any], created: Optional[float] = None) -> None:
    now = time.time()
    with _LOCK:
        _ensure()
        try:
            with _connect() as con:
                con.execute(
                    "INSERT INTO deep_jobs(id, created, updated, status, snapshot) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET updated = excluded.updated, status = excluded.status, snapshot = excluded.snapshot",
                    (job_id, created or now, now, status, json.dumps(snapshot, ensure_ascii=False)),
                )
        except sqlite3.Error as exc:
            logger.debug("job_save %s failed: %s", job_id, exc)


def job_load(job_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        _ensure()
        try:
            with _connect() as con:
                row = con.execute("SELECT created, updated, status, snapshot FROM deep_jobs WHERE id = ?", (job_id,)).fetchone()
        except sqlite3.Error:
            return None
    if not row:
        return None
    created, updated, status, snapshot = row
    try:
        data = json.loads(snapshot)
    except json.JSONDecodeError:
        data = {}
    return {"created": created, "updated": updated, "status": status, "snapshot": data}


def jobs_unfinished() -> List[str]:
    with _LOCK:
        _ensure()
        try:
            with _connect() as con:
                rows = con.execute(
                    "SELECT id FROM deep_jobs WHERE status NOT IN ('done', 'failed', 'cancelled')"
                ).fetchall()
        except sqlite3.Error:
            return []
    return [r[0] for r in rows]


def event_append(job_id: str, seq: int, event: Dict[str, Any]) -> None:
    with _LOCK:
        _ensure()
        try:
            with _connect() as con:
                con.execute("INSERT OR REPLACE INTO deep_events(job_id, seq, event) VALUES (?, ?, ?)",
                            (job_id, seq, json.dumps(event, ensure_ascii=False)))
        except sqlite3.Error as exc:
            logger.debug("event_append %s/%s failed: %s", job_id, seq, exc)


def events_after(job_id: str, after: int = 0) -> List[Dict[str, Any]]:
    with _LOCK:
        _ensure()
        try:
            with _connect() as con:
                rows = con.execute(
                    "SELECT event FROM deep_events WHERE job_id = ? AND seq > ? ORDER BY seq", (job_id, after)
                ).fetchall()
        except sqlite3.Error:
            return []
    out: List[Dict[str, Any]] = []
    for (raw,) in rows:
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def jobs_prune(older_than_s: float) -> int:
    cutoff = time.time() - older_than_s
    with _LOCK:
        _ensure()
        try:
            with _connect() as con:
                ids = [r[0] for r in con.execute("SELECT id FROM deep_jobs WHERE updated < ?", (cutoff,)).fetchall()]
                for job_id in ids:
                    con.execute("DELETE FROM deep_events WHERE job_id = ?", (job_id,))
                    con.execute("DELETE FROM deep_jobs WHERE id = ?", (job_id,))
                return len(ids)
        except sqlite3.Error:
            return 0
