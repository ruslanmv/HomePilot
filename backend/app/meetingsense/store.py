"""MeetingSense persistence (batch MS2).

Four tables in the app's existing SQLite file, created only when MeetingSense is enabled.
Nothing here alters a table that already exists — the ``ms_`` prefix is the whole isolation
story, and ``migrate()`` is a no-op on every install that never turns the feature on.

The database path comes from ``storage._get_db_path()`` rather than from a second reading of
``SQLITE_PATH``. That function does more than read a variable: it probes the directory for
write permission and falls back to a local path when the configured one is read-only. A
second implementation would put meetings in a different file from messages on exactly the
installs where that matters.

Every write is its own connection, opened and closed, which is how ``storage.py`` does it.
That is not the fastest possible design and it is the one that matches the neighbours; a
connection pool here would be a second concurrency model in one process.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

#: Bumped when a migration adds something. Recorded so a later batch can tell an old file
#: from a new one without inspecting the schema — MS16 adds columns to ``ms_meetings``.
SCHEMA_VERSION = 1

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS ms_meetings(
        id              TEXT PRIMARY KEY,
        conversation_id TEXT,
        project_id      TEXT,
        title           TEXT,
        source          TEXT,
        started_at      REAL NOT NULL,
        ended_at        REAL,
        audio_mode      TEXT,
        retention       TEXT NOT NULL DEFAULT 'text',
        status          TEXT NOT NULL DEFAULT 'live',
        summary_json    TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_segments(
        id         TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL,
        t0_ms      INTEGER NOT NULL,
        t1_ms      INTEGER,
        speaker    TEXT,
        text       TEXT NOT NULL,
        conf       REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_keyframes(
        id         TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL,
        t_ms       INTEGER NOT NULL,
        url        TEXT NOT NULL,
        hash       TEXT,
        caption    TEXT,
        ocr_text   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_notes(
        meeting_id TEXT NOT NULL,
        version    INTEGER NOT NULL,
        json       TEXT NOT NULL,
        updated_at REAL NOT NULL,
        PRIMARY KEY (meeting_id, version)
    )
    """,
    # A meeting is read back in time order constantly — the card, the export, the slide/
    # transcript join. Without these, every read is a scan of every segment ever recorded.
    "CREATE INDEX IF NOT EXISTS ix_ms_segments_meeting_t0 ON ms_segments(meeting_id, t0_ms)",
    "CREATE INDEX IF NOT EXISTS ix_ms_keyframes_meeting_t ON ms_keyframes(meeting_id, t_ms)",
    "CREATE INDEX IF NOT EXISTS ix_ms_meetings_conversation ON ms_meetings(conversation_id)",
)


def _connect() -> sqlite3.Connection:
    """A connection to the app's database, with rows that read like dicts.

    Imported inside the function: ``store`` is meant to be importable without pulling in the
    rest of the app, which is what lets the config and unit tests run in isolation.
    """
    from ..storage import _get_db_path

    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    return con


def migrate() -> None:
    """Create the MeetingSense tables. Idempotent, and never called while the flag is off.

    ``CREATE TABLE IF NOT EXISTS`` throughout, so running it against a database that already
    has them is free — which matters because it runs at every startup that has the feature
    enabled rather than through a migration ledger.
    """
    con = _connect()
    try:
        cur = con.cursor()
        for statement in _SCHEMA:
            cur.execute(statement)
        con.commit()
    finally:
        con.close()


def migrate_if_enabled(config) -> bool:
    """Create the tables only when MeetingSense is on. Returns whether it did.

    The point of the guard: an install that never enables MeetingSense should not grow four
    tables it will never use. ``migrate()`` stays public so a test can call it directly.
    """
    if not getattr(config, "enabled", False):
        return False
    migrate()
    return True


def tables_exist() -> bool:
    """Whether the MeetingSense tables are present — for the status endpoint and for tests."""
    con = _connect()
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ms_%'"
        ).fetchall()
        return {r["name"] for r in rows} >= {"ms_meetings", "ms_segments", "ms_keyframes", "ms_notes"}
    finally:
        con.close()


# ── meetings ────────────────────────────────────────────────────────────────


def create_meeting(
    *,
    conversation_id: str,
    project_id: Optional[str] = None,
    title: Optional[str] = None,
    source: Optional[str] = None,
    audio_mode: Optional[str] = None,
    retention: str = "text",
    meeting_id: Optional[str] = None,
    started_at: Optional[float] = None,
) -> str:
    """Open a meeting row and return its id."""
    mid = meeting_id or uuid.uuid4().hex
    con = _connect()
    try:
        con.execute(
            """
            INSERT INTO ms_meetings
                (id, conversation_id, project_id, title, source, started_at, audio_mode,
                 retention, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'live')
            """,
            (
                mid,
                conversation_id,
                project_id,
                title,
                source,
                started_at if started_at is not None else time.time(),
                audio_mode,
                retention,
            ),
        )
        con.commit()
    finally:
        con.close()
    return mid


def end_meeting(meeting_id: str, *, ended_at: Optional[float] = None, summary: Any = None) -> None:
    """Close a meeting. Safe to call twice — a second stop must not reopen or duplicate."""
    con = _connect()
    try:
        con.execute(
            "UPDATE ms_meetings SET ended_at = ?, status = 'ended', summary_json = ? WHERE id = ?",
            (
                ended_at if ended_at is not None else time.time(),
                json.dumps(summary) if summary is not None else None,
                meeting_id,
            ),
        )
        con.commit()
    finally:
        con.close()


def get_meeting(meeting_id: str) -> Optional[Dict[str, Any]]:
    con = _connect()
    try:
        row = con.execute("SELECT * FROM ms_meetings WHERE id = ?", (meeting_id,)).fetchone()
        if row is None:
            return None
        meeting = dict(row)
        raw = meeting.pop("summary_json", None)
        meeting["summary"] = json.loads(raw) if raw else None
        return meeting
    finally:
        con.close()


def list_meetings(*, conversation_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    con = _connect()
    try:
        if conversation_id:
            rows = con.execute(
                "SELECT * FROM ms_meetings WHERE conversation_id = ? ORDER BY started_at DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM ms_meetings ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ── segments ────────────────────────────────────────────────────────────────


def add_segments(meeting_id: str, segments: Iterable[Dict[str, Any]]) -> List[str]:
    """Append transcript segments. Append-only: a transcript is never rewritten.

    ``t1_ms`` may be ``None`` — MS1's contract, and it means the provider did not measure the
    end rather than that the segment is instantaneous. Storing a zero here would put a wrong
    number in front of a reader who has no way to tell it from a real one.
    """
    rows = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        rows.append(
            (
                seg.get("id") or uuid.uuid4().hex,
                meeting_id,
                int(seg.get("t0_ms") or 0),
                None if seg.get("t1_ms") is None else int(seg["t1_ms"]),
                seg.get("speaker"),
                text,
                seg.get("conf"),
            )
        )
    if not rows:
        return []
    con = _connect()
    try:
        con.executemany(
            "INSERT INTO ms_segments(id, meeting_id, t0_ms, t1_ms, speaker, text, conf)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        con.commit()
    finally:
        con.close()
    return [r[0] for r in rows]


def get_segments(
    meeting_id: str, *, t0_ms: Optional[int] = None, t1_ms: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Segments in time order, optionally within a window (the slide/transcript join)."""
    sql = "SELECT * FROM ms_segments WHERE meeting_id = ?"
    args: List[Any] = [meeting_id]
    if t0_ms is not None:
        sql += " AND t0_ms >= ?"
        args.append(t0_ms)
    if t1_ms is not None:
        sql += " AND t0_ms <= ?"
        args.append(t1_ms)
    sql += " ORDER BY t0_ms ASC"
    con = _connect()
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


# ── keyframes ───────────────────────────────────────────────────────────────


def add_keyframe(
    meeting_id: str,
    *,
    t_ms: int,
    url: str,
    hash: Optional[str] = None,
    caption: Optional[str] = None,
    ocr_text: Optional[str] = None,
    keyframe_id: Optional[str] = None,
) -> str:
    kid = keyframe_id or uuid.uuid4().hex
    con = _connect()
    try:
        con.execute(
            "INSERT INTO ms_keyframes(id, meeting_id, t_ms, url, hash, caption, ocr_text)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kid, meeting_id, int(t_ms), url, hash, caption, ocr_text),
        )
        con.commit()
    finally:
        con.close()
    return kid


def set_keyframe_caption(keyframe_id: str, caption: str, ocr_text: Optional[str] = None) -> None:
    """Captions arrive seconds after the frame — the vision model is asynchronous."""
    con = _connect()
    try:
        con.execute(
            "UPDATE ms_keyframes SET caption = ?, ocr_text = COALESCE(?, ocr_text) WHERE id = ?",
            (caption, ocr_text, keyframe_id),
        )
        con.commit()
    finally:
        con.close()


def get_keyframes(meeting_id: str) -> List[Dict[str, Any]]:
    con = _connect()
    try:
        rows = con.execute(
            "SELECT * FROM ms_keyframes WHERE meeting_id = ? ORDER BY t_ms ASC", (meeting_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ── notes ───────────────────────────────────────────────────────────────────


def save_notes(meeting_id: str, notes: Any, *, version: Optional[int] = None) -> int:
    """Store a notes version and return it.

    Versioned rather than overwritten. The card corrects by appending and striking through,
    which needs the previous version to still exist; and a notes engine that merges deltas is
    much easier to debug when every step it took is on disk.
    """
    con = _connect()
    try:
        if version is None:
            row = con.execute(
                "SELECT MAX(version) AS v FROM ms_notes WHERE meeting_id = ?", (meeting_id,)
            ).fetchone()
            version = int((row["v"] or 0)) + 1
        con.execute(
            "INSERT OR REPLACE INTO ms_notes(meeting_id, version, json, updated_at)"
            " VALUES (?, ?, ?, ?)",
            (meeting_id, version, json.dumps(notes), time.time()),
        )
        con.commit()
        return version
    finally:
        con.close()


def get_notes(meeting_id: str, *, version: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The newest notes version, or a named one."""
    con = _connect()
    try:
        if version is None:
            row = con.execute(
                "SELECT * FROM ms_notes WHERE meeting_id = ? ORDER BY version DESC LIMIT 1",
                (meeting_id,),
            ).fetchone()
        else:
            row = con.execute(
                "SELECT * FROM ms_notes WHERE meeting_id = ? AND version = ?",
                (meeting_id, version),
            ).fetchone()
        if row is None:
            return None
        return {"version": row["version"], "updated_at": row["updated_at"], "notes": json.loads(row["json"])}
    finally:
        con.close()


# ── deletion ────────────────────────────────────────────────────────────────


def delete_meeting(meeting_id: str) -> Dict[str, int]:
    """Remove a meeting and everything under it. Returns what was removed.

    Files are not touched here — the caller owns the upload directory and knows the retention
    mode. Counting the rows is what lets the caller report a real number rather than "done".
    """
    con = _connect()
    try:
        counts = {
            "segments": con.execute(
                "SELECT COUNT(*) c FROM ms_segments WHERE meeting_id = ?", (meeting_id,)
            ).fetchone()["c"],
            "keyframes": con.execute(
                "SELECT COUNT(*) c FROM ms_keyframes WHERE meeting_id = ?", (meeting_id,)
            ).fetchone()["c"],
            "notes": con.execute(
                "SELECT COUNT(*) c FROM ms_notes WHERE meeting_id = ?", (meeting_id,)
            ).fetchone()["c"],
        }
        for table in ("ms_segments", "ms_keyframes", "ms_notes"):
            con.execute(f"DELETE FROM {table} WHERE meeting_id = ?", (meeting_id,))
        cur = con.execute("DELETE FROM ms_meetings WHERE id = ?", (meeting_id,))
        counts["meetings"] = cur.rowcount
        con.commit()
        return counts
    finally:
        con.close()
