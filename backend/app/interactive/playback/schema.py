"""
Defensive DDL for the live-play subsystem.

Rather than editing ``store.py``'s canonical ``_DDL`` list, we
apply one extra ``CREATE TABLE IF NOT EXISTS`` from inside
the subpackage so the base interactive schema stays untouched.
Every playback entry-point calls ``ensure_playback_schema()``
once per session; the guard flag makes repeat calls a no-op.

Table: ``ix_scene_queue``
  id           TEXT PRIMARY KEY
  session_id   TEXT NOT NULL
  turn_id      TEXT DEFAULT ''           chat turn that produced this job
  status       TEXT NOT NULL DEFAULT 'pending'  pending | rendering | ready | failed
  job_id       TEXT DEFAULT ''           opaque id returned by the render backend
  asset_id     TEXT DEFAULT ''           final file id once status='ready'
  prompt       TEXT NOT NULL             scene prompt fed to the renderer
  duration_sec INTEGER DEFAULT 5
  error        TEXT DEFAULT ''           populated only on status='failed'
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
  updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
"""
from __future__ import annotations

from .. import store


_DDL = [
    """
    CREATE TABLE IF NOT EXISTS ix_scene_queue (
        id            TEXT PRIMARY KEY,
        session_id    TEXT NOT NULL,
        turn_id       TEXT DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'pending',
        job_id        TEXT DEFAULT '',
        asset_id      TEXT DEFAULT '',
        prompt        TEXT NOT NULL,
        duration_sec  INTEGER DEFAULT 5,
        error         TEXT DEFAULT '',
        created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_scene_queue_session ON ix_scene_queue(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_ix_scene_queue_status  ON ix_scene_queue(status)",
]

_INITIALIZED = False


def ensure_playback_schema() -> None:
    """Idempotent: creates the ix_scene_queue table on first call."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    store.ensure_schema()
    with store._conn() as con:
        cur = con.cursor()
        for stmt in _DDL:
            cur.execute(stmt)
        con.commit()
    _INITIALIZED = True


def _reset_for_tests() -> None:
    """Clear the initialized flag — only the playback test suite
    calls this, after tearing down its temp DB path so the next
    test re-creates the table on the fresh file."""
    global _INITIALIZED
    _INITIALIZED = False
