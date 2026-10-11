"""Meetings Library persistence — companion tables beside MeetingSense's own.

Additive only. Nothing here alters an ``ms_`` table MeetingSense created; it adds tables
next to them and keys them by the same meeting id, so a meeting is one row in ``ms_meetings``
whichever way it arrived — recorded live, imported, synced from a folder or scheduled.

The connection is MeetingSense's (``store._connect``) so the library writes to the same
database file, and so a test that redirects that one function redirects both.

Rollback is "turn the flag off": the tables stay, every row stays, and turning the flag on
again finds them as they were.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .. import store

LIBRARY_SCHEMA_VERSION = 1

_TABLES = (
    # One row per meeting that the library knows more about than ms_meetings can hold:
    # where it came from, whether it has audio and a transcript, what it is about.
    """
    CREATE TABLE IF NOT EXISTS ms_library_entries(
        meeting_id        TEXT PRIMARY KEY,
        origin_type       TEXT NOT NULL,
        owner_user_id     TEXT NOT NULL DEFAULT '',
        category          TEXT,
        description       TEXT,
        scheduled_for     REAL,
        recording_plan    TEXT,
        recording_state   TEXT NOT NULL DEFAULT 'none',
        transcript_state  TEXT NOT NULL DEFAULT 'none',
        summary_state     TEXT NOT NULL DEFAULT 'none',
        duration_ms       INTEGER,
        media_present     INTEGER NOT NULL DEFAULT 0,
        outputs_json      TEXT,
        raw_metadata_json TEXT,
        warnings_json     TEXT,
        hidden_at         REAL,
        created_at        REAL NOT NULL,
        updated_at        REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_library_sources(
        id              TEXT PRIMARY KEY,
        kind            TEXT NOT NULL,
        display_name    TEXT NOT NULL,
        path            TEXT NOT NULL,
        resolved_path   TEXT NOT NULL,
        owner_user_id   TEXT NOT NULL DEFAULT '',
        enabled         INTEGER NOT NULL DEFAULT 1,
        project_id      TEXT,
        last_scan_at    REAL,
        last_success_at REAL,
        last_error      TEXT,
        counts_json     TEXT,
        created_at      REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_library_assets(
        id                TEXT PRIMARY KEY,
        meeting_id        TEXT,
        source_id         TEXT NOT NULL,
        origin_type       TEXT NOT NULL,
        relative_path     TEXT NOT NULL,
        original_name     TEXT NOT NULL,
        kind              TEXT NOT NULL,
        role              TEXT NOT NULL DEFAULT 'primary',
        sha256            TEXT NOT NULL,
        mime              TEXT,
        size_bytes        INTEGER NOT NULL DEFAULT 0,
        storage_ref       TEXT,
        media_duration_ms INTEGER,
        source_available  INTEGER NOT NULL DEFAULT 1,
        metadata_json     TEXT,
        created_at        REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_library_imports(
        id              TEXT PRIMARY KEY,
        owner_user_id   TEXT NOT NULL DEFAULT '',
        source_id       TEXT NOT NULL,
        idempotency_key TEXT,
        status          TEXT NOT NULL,
        manifest_json   TEXT,
        staging_dir     TEXT,
        error           TEXT,
        created_at      REAL NOT NULL,
        committed_at    REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_library_jobs(
        id          TEXT PRIMARY KEY,
        meeting_id  TEXT NOT NULL,
        type        TEXT NOT NULL,
        state       TEXT NOT NULL,
        stage       TEXT,
        progress    REAL NOT NULL DEFAULT 0,
        attempt     INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 2,
        options_json TEXT,
        diagnostic_json TEXT,
        error       TEXT,
        lease_until REAL,
        created_at  REAL NOT NULL,
        started_at  REAL,
        finished_at REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_meeting_project_links(
        meeting_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        kind       TEXT NOT NULL DEFAULT 'linked',
        created_at REAL NOT NULL,
        PRIMARY KEY (meeting_id, project_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_library_origin_links(
        origin_type TEXT NOT NULL,
        origin_id   TEXT NOT NULL,
        meeting_id  TEXT NOT NULL,
        created_at  REAL NOT NULL,
        PRIMARY KEY (origin_type, origin_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_transcript_versions(
        id            TEXT PRIMARY KEY,
        meeting_id    TEXT NOT NULL,
        origin        TEXT NOT NULL,
        source_ref    TEXT,
        provider      TEXT,
        model         TEXT,
        language      TEXT,
        timing        TEXT NOT NULL,
        active        INTEGER NOT NULL DEFAULT 0,
        segment_count INTEGER NOT NULL DEFAULT 0,
        note          TEXT,
        created_at    REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_transcript_version_segments(
        version_id TEXT NOT NULL,
        seq        INTEGER NOT NULL,
        t0_ms      INTEGER NOT NULL,
        t1_ms      INTEGER,
        speaker    TEXT,
        text       TEXT NOT NULL,
        conf       REAL,
        PRIMARY KEY (version_id, seq)
    )
    """,
    # What a folder scan has seen, so "finished writing" can be told from "still being
    # written": a file is imported only once its size and mtime have held still.
    """
    CREATE TABLE IF NOT EXISTS ms_library_sync_seen(
        source_id     TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        size_bytes    INTEGER NOT NULL,
        mtime         REAL NOT NULL,
        first_seen_at REAL NOT NULL,
        PRIMARY KEY (source_id, relative_path)
    )
    """,
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_ms_lib_assets_meeting ON ms_library_assets(meeting_id, kind)",
    "CREATE INDEX IF NOT EXISTS ix_ms_lib_assets_sha ON ms_library_assets(sha256)",
    "CREATE INDEX IF NOT EXISTS ix_ms_lib_assets_source ON ms_library_assets(source_id, relative_path)",
    "CREATE INDEX IF NOT EXISTS ix_ms_lib_jobs_state ON ms_library_jobs(state, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_ms_lib_jobs_meeting ON ms_library_jobs(meeting_id)",
    "CREATE INDEX IF NOT EXISTS ix_ms_lib_links_project ON ms_meeting_project_links(project_id)",
    "CREATE INDEX IF NOT EXISTS ix_ms_lib_origin_meeting ON ms_library_origin_links(meeting_id)",
    "CREATE INDEX IF NOT EXISTS ix_ms_tv_meeting ON ms_transcript_versions(meeting_id, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_ms_lib_imports_key ON ms_library_imports(owner_user_id, idempotency_key)",
)

#: The states a transcript can be in. Recording and transcript are separate fields: an
#: imported recording keeps its audio whatever happens to its transcription.
TRANSCRIPT_STATES = (
    "none", "imported", "queued", "transcribing", "ready", "ready_warnings",
    "failed", "needs_setup", "no_speech", "transcript_only",
)
RECORDING_STATES = ("none", "awaiting", "recording", "present", "unavailable")
JOB_STATES = ("queued", "running", "done", "failed", "cancelled", "needs_setup")

_migrated_paths: set = set()


def _connect():
    return store._connect()


def _now() -> float:
    return time.time()


def _dumps(value: Any) -> Optional[str]:
    return None if value is None else json.dumps(value)


def _loads(raw: Optional[str], default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def migrate() -> None:
    """Create MeetingSense's tables (idempotent) and the library's beside them, then seed
    project links from the ``project_id`` meetings already carry. Safe to run every start."""
    store.migrate()
    con = _connect()
    try:
        cur = con.cursor()
        for statement in _TABLES:
            cur.execute(statement)
        for statement in _INDEXES:
            cur.execute(statement)
        # Every meeting recorded in a project is linked to it — once, idempotently, and the
        # ms_meetings.project_id column stays exactly as it was.
        cur.execute(
            "INSERT OR IGNORE INTO ms_meeting_project_links(meeting_id, project_id, kind, created_at)"
            " SELECT id, project_id, 'primary', started_at FROM ms_meetings"
            " WHERE project_id IS NOT NULL AND project_id != ''"
        )
        con.commit()
    finally:
        con.close()


def ensure_migrated() -> None:
    """``migrate`` once per database file per process (the routes call this on every request)."""
    try:
        from ...storage import _get_db_path  # noqa: PLC0415

        key = _get_db_path()
    except Exception:  # noqa: BLE001
        key = "default"
    key = f"{key}:{id(store._connect)}"
    if key in _migrated_paths:
        return
    migrate()
    _migrated_paths.add(key)


# ── entries ─────────────────────────────────────────────────────────────────


def _entry_row(row) -> Dict[str, Any]:
    out = dict(row)
    out["outputs"] = _loads(out.pop("outputs_json", None), None)
    out["raw_metadata"] = _loads(out.pop("raw_metadata_json", None), None)
    out["warnings"] = _loads(out.pop("warnings_json", None), []) or []
    return out


def create_meeting_entry(
    *,
    title: str,
    origin_type: str,
    owner_user_id: str = "",
    started_at: Optional[float] = None,
    ended_at: Optional[float] = None,
    status: str = "ended",
    source: Optional[str] = None,
    project_id: Optional[str] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    scheduled_for: Optional[float] = None,
    recording_plan: Optional[str] = None,
    recording_state: str = "none",
    transcript_state: str = "none",
    duration_ms: Optional[int] = None,
    outputs: Any = None,
    raw_metadata: Any = None,
    warnings: Optional[Sequence[str]] = None,
    meeting_id: Optional[str] = None,
) -> str:
    """Create a finished (or scheduled) meeting **without** a live session.

    ``store.create_meeting`` opens a row as ``live``, which is right for the recorder and
    wrong here: an imported recording is already over, and a scheduled meeting has not
    started. Both get a meeting row of their own with no conversation behind it.
    """
    mid = meeting_id or uuid.uuid4().hex
    now = _now()
    start = float(started_at if started_at is not None else (scheduled_for or now))
    con = _connect()
    try:
        con.execute(
            "INSERT INTO ms_meetings(id, conversation_id, project_id, title, source, started_at,"
            " ended_at, audio_mode, retention, status) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'text', ?)",
            (mid, project_id or None, title, source, start, ended_at, "import", status),
        )
        con.execute(
            "INSERT INTO ms_library_entries(meeting_id, origin_type, owner_user_id, category,"
            " description, scheduled_for, recording_plan, recording_state, transcript_state,"
            " summary_state, duration_ms, media_present, outputs_json, raw_metadata_json,"
            " warnings_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'none', ?, ?, ?, ?, ?, ?, ?)",
            (
                mid, origin_type, owner_user_id or "", category, description, scheduled_for,
                recording_plan, recording_state, transcript_state, duration_ms,
                1 if recording_state == "present" else 0, _dumps(outputs), _dumps(raw_metadata),
                _dumps(list(warnings or [])), now, now,
            ),
        )
        if project_id:
            con.execute(
                "INSERT OR IGNORE INTO ms_meeting_project_links(meeting_id, project_id, kind, created_at)"
                " VALUES (?, ?, 'primary', ?)",
                (mid, project_id, now),
            )
        con.commit()
    finally:
        con.close()
    return mid


def ensure_entry(meeting_id: str, *, origin_type: str = "meetingsense", owner_user_id: str = "") -> None:
    """Give a meeting that predates the library an entry row (for edits like a category)."""
    now = _now()
    con = _connect()
    try:
        con.execute(
            "INSERT OR IGNORE INTO ms_library_entries(meeting_id, origin_type, owner_user_id,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (meeting_id, origin_type, owner_user_id or "", now, now),
        )
        con.commit()
    finally:
        con.close()


_ENTRY_FIELDS = {
    "category", "description", "scheduled_for", "recording_plan", "recording_state",
    "transcript_state", "summary_state", "duration_ms", "media_present", "hidden_at",
}


def update_entry(meeting_id: str, *, outputs: Any = None, raw_metadata: Any = None,
                 warnings: Optional[Sequence[str]] = None, **fields: Any) -> None:
    sets: List[str] = []
    args: List[Any] = []
    for key, value in fields.items():
        if key not in _ENTRY_FIELDS:
            raise ValueError(f"not an entry field: {key}")
        sets.append(f"{key} = ?")
        args.append(value)
    if outputs is not None:
        sets.append("outputs_json = ?")
        args.append(_dumps(outputs))
    if raw_metadata is not None:
        sets.append("raw_metadata_json = ?")
        args.append(_dumps(raw_metadata))
    if warnings is not None:
        sets.append("warnings_json = ?")
        args.append(_dumps(list(warnings)))
    if not sets:
        return
    sets.append("updated_at = ?")
    args.append(_now())
    con = _connect()
    try:
        con.execute(f"UPDATE ms_library_entries SET {', '.join(sets)} WHERE meeting_id = ?", args + [meeting_id])
        con.commit()
    finally:
        con.close()


def add_warning(meeting_id: str, warning: str) -> None:
    entry = get_entry(meeting_id)
    if entry is None:
        return
    warnings = list(entry.get("warnings") or [])
    if warning not in warnings:
        warnings.append(warning)
        update_entry(meeting_id, warnings=warnings)


def get_entry(meeting_id: str) -> Optional[Dict[str, Any]]:
    con = _connect()
    try:
        row = con.execute("SELECT * FROM ms_library_entries WHERE meeting_id = ?", (meeting_id,)).fetchone()
        return _entry_row(row) if row else None
    finally:
        con.close()


def entries_by_id(meeting_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = list(meeting_ids)
    if not ids:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    con = _connect()
    try:
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            rows = con.execute(
                f"SELECT * FROM ms_library_entries WHERE meeting_id IN ({','.join('?' * len(part))})", part
            ).fetchall()
            for row in rows:
                out[row["meeting_id"]] = _entry_row(row)
    finally:
        con.close()
    return out


# ── project links ───────────────────────────────────────────────────────────


def project_links(meeting_ids: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
    ids = list(meeting_ids)
    out: Dict[str, List[Dict[str, Any]]] = {}
    if not ids:
        return out
    con = _connect()
    try:
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            rows = con.execute(
                "SELECT * FROM ms_meeting_project_links WHERE meeting_id IN"
                f" ({','.join('?' * len(part))}) ORDER BY kind = 'primary' DESC, created_at ASC",
                part,
            ).fetchall()
            for row in rows:
                out.setdefault(row["meeting_id"], []).append(dict(row))
    finally:
        con.close()
    return out


def set_project_links(meeting_id: str, project_ids: Sequence[str]) -> List[str]:
    """Make a meeting's linked projects exactly ``project_ids``. Never copies the meeting.

    The primary link (the project a meeting was recorded in) is kept as ``primary`` if it
    stays; ``ms_meetings.project_id`` is left as it was, which keeps every pre-library reader
    of that column answering what it always answered.
    """
    wanted = [p for p in dict.fromkeys(str(p).strip() for p in project_ids) if p]
    now = _now()
    con = _connect()
    try:
        existing = {r["project_id"] for r in con.execute(
            "SELECT project_id FROM ms_meeting_project_links WHERE meeting_id = ?", (meeting_id,)
        ).fetchall()}
        for pid in existing - set(wanted):
            con.execute("DELETE FROM ms_meeting_project_links WHERE meeting_id = ? AND project_id = ?", (meeting_id, pid))
        for pid in wanted:
            if pid not in existing:
                con.execute(
                    "INSERT INTO ms_meeting_project_links(meeting_id, project_id, kind, created_at)"
                    " VALUES (?, ?, 'linked', ?)",
                    (meeting_id, pid, now),
                )
        con.commit()
    finally:
        con.close()
    return wanted


# ── origin links (dedup) ────────────────────────────────────────────────────


def origin_meeting(origin_type: str, origin_id: str) -> Optional[str]:
    con = _connect()
    try:
        row = con.execute(
            "SELECT meeting_id FROM ms_library_origin_links WHERE origin_type = ? AND origin_id = ?",
            (origin_type, origin_id),
        ).fetchone()
        return row["meeting_id"] if row else None
    finally:
        con.close()


def link_origin(origin_type: str, origin_id: str, meeting_id: str) -> None:
    con = _connect()
    try:
        con.execute(
            "INSERT OR IGNORE INTO ms_library_origin_links(origin_type, origin_id, meeting_id, created_at)"
            " VALUES (?, ?, ?, ?)",
            (origin_type, origin_id, meeting_id, _now()),
        )
        con.commit()
    finally:
        con.close()


# ── assets ──────────────────────────────────────────────────────────────────


def add_asset(**fields: Any) -> str:
    aid = fields.pop("id", None) or uuid.uuid4().hex
    metadata = fields.pop("metadata", None)
    cols = [
        "meeting_id", "source_id", "origin_type", "relative_path", "original_name", "kind", "role",
        "sha256", "mime", "size_bytes", "storage_ref", "media_duration_ms",
    ]
    values = [fields.get(c) for c in cols]
    if values[cols.index("role")] is None:
        values[cols.index("role")] = "primary"
    if values[cols.index("size_bytes")] is None:
        values[cols.index("size_bytes")] = 0
    con = _connect()
    try:
        con.execute(
            f"INSERT INTO ms_library_assets(id, {', '.join(cols)}, metadata_json, created_at)"
            f" VALUES (?, {', '.join('?' * len(cols))}, ?, ?)",
            [aid] + values + [_dumps(metadata), _now()],
        )
        con.commit()
    finally:
        con.close()
    return aid


def _asset_row(row) -> Dict[str, Any]:
    out = dict(row)
    out["metadata"] = _loads(out.pop("metadata_json", None), {}) or {}
    return out


def assets_for(meeting_id: str) -> List[Dict[str, Any]]:
    con = _connect()
    try:
        rows = con.execute(
            "SELECT * FROM ms_library_assets WHERE meeting_id = ? ORDER BY kind, role = 'primary' DESC, created_at",
            (meeting_id,),
        ).fetchall()
        return [_asset_row(r) for r in rows]
    finally:
        con.close()


def get_asset(asset_id: str) -> Optional[Dict[str, Any]]:
    con = _connect()
    try:
        row = con.execute("SELECT * FROM ms_library_assets WHERE id = ?", (asset_id,)).fetchone()
        return _asset_row(row) if row else None
    finally:
        con.close()


def update_asset(asset_id: str, *, metadata: Any = None, **fields: Any) -> None:
    allowed = {"relative_path", "source_available", "media_duration_ms", "storage_ref", "meeting_id"}
    sets, args = [], []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"not an asset field: {key}")
        sets.append(f"{key} = ?")
        args.append(value)
    if metadata is not None:
        sets.append("metadata_json = ?")
        args.append(_dumps(metadata))
    if not sets:
        return
    con = _connect()
    try:
        con.execute(f"UPDATE ms_library_assets SET {', '.join(sets)} WHERE id = ?", args + [asset_id])
        con.commit()
    finally:
        con.close()


def assets_with_sha(sha256: str) -> List[Dict[str, Any]]:
    con = _connect()
    try:
        rows = con.execute(
            "SELECT * FROM ms_library_assets WHERE sha256 = ? AND meeting_id IS NOT NULL", (sha256,)
        ).fetchall()
        return [_asset_row(r) for r in rows]
    finally:
        con.close()


def assets_for_source(source_id: str) -> List[Dict[str, Any]]:
    con = _connect()
    try:
        rows = con.execute("SELECT * FROM ms_library_assets WHERE source_id = ?", (source_id,)).fetchall()
        return [_asset_row(r) for r in rows]
    finally:
        con.close()


# ── imports ─────────────────────────────────────────────────────────────────


def create_import(*, owner_user_id: str, source_id: str, manifest: Any, staging_dir: str,
                  idempotency_key: Optional[str] = None, import_id: Optional[str] = None) -> str:
    iid = import_id or uuid.uuid4().hex
    con = _connect()
    try:
        con.execute(
            "INSERT INTO ms_library_imports(id, owner_user_id, source_id, idempotency_key, status,"
            " manifest_json, staging_dir, created_at) VALUES (?, ?, ?, ?, 'previewed', ?, ?, ?)",
            (iid, owner_user_id or "", source_id, idempotency_key, _dumps(manifest), staging_dir, _now()),
        )
        con.commit()
    finally:
        con.close()
    return iid


def get_import(import_id: str) -> Optional[Dict[str, Any]]:
    con = _connect()
    try:
        row = con.execute("SELECT * FROM ms_library_imports WHERE id = ?", (import_id,)).fetchone()
        if not row:
            return None
        out = dict(row)
        out["manifest"] = _loads(out.pop("manifest_json", None), {}) or {}
        return out
    finally:
        con.close()


def import_by_key(owner_user_id: str, key: str) -> Optional[Dict[str, Any]]:
    con = _connect()
    try:
        row = con.execute(
            "SELECT id FROM ms_library_imports WHERE owner_user_id = ? AND idempotency_key = ?",
            (owner_user_id or "", key),
        ).fetchone()
    finally:
        con.close()
    return get_import(row["id"]) if row else None


def update_import(import_id: str, *, status: Optional[str] = None, manifest: Any = None,
                  error: Optional[str] = None, committed: bool = False,
                  idempotency_key: Optional[str] = None) -> None:
    sets, args = [], []
    if status is not None:
        sets.append("status = ?")
        args.append(status)
    if manifest is not None:
        sets.append("manifest_json = ?")
        args.append(_dumps(manifest))
    if error is not None:
        sets.append("error = ?")
        args.append(error)
    if committed:
        sets.append("committed_at = ?")
        args.append(_now())
    if idempotency_key is not None:
        sets.append("idempotency_key = ?")
        args.append(idempotency_key)
    if not sets:
        return
    con = _connect()
    try:
        con.execute(f"UPDATE ms_library_imports SET {', '.join(sets)} WHERE id = ?", args + [import_id])
        con.commit()
    finally:
        con.close()


# ── jobs ────────────────────────────────────────────────────────────────────


def create_job(meeting_id: str, type_: str, *, options: Any = None, max_attempts: int = 2) -> str:
    """Queue a job, unless an identical one is already queued or running (idempotent)."""
    con = _connect()
    try:
        row = con.execute(
            "SELECT id FROM ms_library_jobs WHERE meeting_id = ? AND type = ? AND state IN ('queued', 'running')",
            (meeting_id, type_),
        ).fetchone()
        if row:
            return row["id"]
        jid = uuid.uuid4().hex
        con.execute(
            "INSERT INTO ms_library_jobs(id, meeting_id, type, state, stage, progress, attempt,"
            " max_attempts, options_json, created_at) VALUES (?, ?, ?, 'queued', 'queued', 0, 0, ?, ?, ?)",
            (jid, meeting_id, type_, max_attempts, _dumps(options), _now()),
        )
        con.commit()
        return jid
    finally:
        con.close()


def _job_row(row) -> Dict[str, Any]:
    out = dict(row)
    out["options"] = _loads(out.pop("options_json", None), {}) or {}
    out["diagnostic"] = _loads(out.pop("diagnostic_json", None), {}) or {}
    return out


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    con = _connect()
    try:
        row = con.execute("SELECT * FROM ms_library_jobs WHERE id = ?", (job_id,)).fetchone()
        return _job_row(row) if row else None
    finally:
        con.close()


def list_jobs(*, meeting_id: Optional[str] = None, states: Optional[Sequence[str]] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM ms_library_jobs WHERE 1=1"
    args: List[Any] = []
    if meeting_id:
        sql += " AND meeting_id = ?"
        args.append(meeting_id)
    if states:
        sql += f" AND state IN ({','.join('?' * len(states))})"
        args.extend(states)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(int(limit))
    con = _connect()
    try:
        return [_job_row(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def lease_next_job(*, lease_s: float = 600.0) -> Optional[Dict[str, Any]]:
    """Take the oldest queued job (or one whose lease ran out — a crashed worker's)."""
    now = _now()
    con = _connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM ms_library_jobs WHERE state = 'queued'"
            " OR (state = 'running' AND lease_until IS NOT NULL AND lease_until < ?)"
            " ORDER BY created_at ASC LIMIT 1",
            (now,),
        ).fetchone()
        if not row:
            con.commit()
            return None
        con.execute(
            "UPDATE ms_library_jobs SET state = 'running', attempt = attempt + 1, lease_until = ?,"
            " started_at = COALESCE(started_at, ?), error = NULL WHERE id = ?",
            (now + lease_s, now, row["id"]),
        )
        con.commit()
    finally:
        con.close()
    return get_job(row["id"])


def update_job(job_id: str, *, state: Optional[str] = None, stage: Optional[str] = None,
               progress: Optional[float] = None, error: Optional[str] = None,
               diagnostic: Any = None, lease_s: Optional[float] = None, finished: bool = False) -> None:
    sets, args = [], []
    if state is not None:
        sets.append("state = ?")
        args.append(state)
    if stage is not None:
        sets.append("stage = ?")
        args.append(stage)
    if progress is not None:
        sets.append("progress = ?")
        args.append(max(0.0, min(1.0, float(progress))))
    if error is not None:
        sets.append("error = ?")
        args.append(error)
    if diagnostic is not None:
        sets.append("diagnostic_json = ?")
        args.append(_dumps(diagnostic))
    if lease_s is not None:
        sets.append("lease_until = ?")
        args.append(_now() + lease_s)
    if finished:
        sets.append("finished_at = ?")
        args.append(_now())
        sets.append("lease_until = NULL")
    if not sets:
        return
    con = _connect()
    try:
        con.execute(f"UPDATE ms_library_jobs SET {', '.join(sets)} WHERE id = ?", args + [job_id])
        con.commit()
    finally:
        con.close()


def job_state(job_id: str) -> Optional[str]:
    con = _connect()
    try:
        row = con.execute("SELECT state FROM ms_library_jobs WHERE id = ?", (job_id,)).fetchone()
        return row["state"] if row else None
    finally:
        con.close()


# ── transcript versions ─────────────────────────────────────────────────────


def create_version(meeting_id: str, segments: Sequence[Dict[str, Any]], *, origin: str, timing: str,
                   source_ref: Optional[str] = None, provider: Optional[str] = None,
                   model: Optional[str] = None, language: Optional[str] = None,
                   note: Optional[str] = None) -> str:
    """Store an immutable transcript version. Not shown until it is published.

    The first version stored for a meeting that already has a transcript (one recorded live)
    is preceded by a ``live`` snapshot of that transcript, so history reads in the order
    things happened and the recorded words are never lost to an edit.
    """
    if origin != "live":
        _snapshot_live(meeting_id)
    vid = uuid.uuid4().hex
    rows = []
    for seq, seg in enumerate(s for s in segments if (s.get("text") or "").strip()):
        rows.append((
            vid, seq, int(seg.get("t0_ms") or 0),
            None if seg.get("t1_ms") is None else int(seg["t1_ms"]),
            seg.get("speaker") or None, str(seg["text"]).strip(), seg.get("conf"),
        ))
    con = _connect()
    try:
        con.execute(
            "INSERT INTO ms_transcript_versions(id, meeting_id, origin, source_ref, provider, model,"
            " language, timing, active, segment_count, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (vid, meeting_id, origin, source_ref, provider, model, language, timing, len(rows), note, _now()),
        )
        con.executemany(
            "INSERT INTO ms_transcript_version_segments(version_id, seq, t0_ms, t1_ms, speaker, text, conf)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        con.commit()
    finally:
        con.close()
    return vid


def _snapshot_live(meeting_id: str) -> None:
    con = _connect()
    try:
        has_versions = con.execute(
            "SELECT 1 FROM ms_transcript_versions WHERE meeting_id = ? LIMIT 1", (meeting_id,)).fetchone()
    finally:
        con.close()
    if has_versions:
        return
    current = store.get_segments(meeting_id)
    if not current:
        return
    snapshot = [{"t0_ms": s["t0_ms"], "t1_ms": s["t1_ms"], "speaker": s.get("speaker"),
                 "text": s["text"], "conf": s.get("conf")} for s in current]
    vid = create_version(meeting_id, snapshot, origin="live", timing="measured",
                         note="The transcript recorded live, kept when another version was added.")
    con = _connect()
    try:  # it is what is shown right now
        con.execute("UPDATE ms_transcript_versions SET active = 1 WHERE id = ?", (vid,))
        con.commit()
    finally:
        con.close()


def list_versions(meeting_id: str) -> List[Dict[str, Any]]:
    con = _connect()
    try:
        rows = con.execute(
            "SELECT * FROM ms_transcript_versions WHERE meeting_id = ? ORDER BY created_at ASC", (meeting_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def version_segments(version_id: str) -> List[Dict[str, Any]]:
    con = _connect()
    try:
        rows = con.execute(
            "SELECT * FROM ms_transcript_version_segments WHERE version_id = ? ORDER BY seq", (version_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def publish_version(meeting_id: str, version_id: str) -> int:
    """Make a version the meeting's transcript. Returns the segments now shown.

    ``ms_segments`` is what every existing reader uses — the card, export, summaries,
    "ask", search — so publishing writes the version there. Whatever was there before is
    first kept as a version of its own (``live`` when the recorder wrote it), so publishing
    never loses a line: the previous transcript is one publish away.
    """
    versions = {v["id"]: v for v in list_versions(meeting_id)}
    if version_id not in versions:
        raise KeyError(version_id)
    rows = version_segments(version_id)
    con = _connect()
    try:
        con.execute("DELETE FROM ms_segments WHERE meeting_id = ?", (meeting_id,))
        con.executemany(
            "INSERT INTO ms_segments(id, meeting_id, t0_ms, t1_ms, speaker, text, conf, seq)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(uuid.uuid4().hex, meeting_id, r["t0_ms"], r["t1_ms"], r["speaker"], r["text"], r["conf"], r["seq"])
             for r in rows],
        )
        con.execute("UPDATE ms_transcript_versions SET active = 0 WHERE meeting_id = ?", (meeting_id,))
        con.execute("UPDATE ms_transcript_versions SET active = 1 WHERE id = ?", (version_id,))
        con.commit()
    finally:
        con.close()
    return len(rows)


# ── folder sources ──────────────────────────────────────────────────────────


def _source_row(row) -> Dict[str, Any]:
    out = dict(row)
    out["counts"] = _loads(out.pop("counts_json", None), {}) or {}
    out["enabled"] = bool(out.get("enabled"))
    return out


def create_source(*, kind: str, display_name: str, path: str, resolved_path: str,
                  owner_user_id: str = "", project_id: Optional[str] = None, enabled: bool = True) -> str:
    sid = uuid.uuid4().hex
    con = _connect()
    try:
        con.execute(
            "INSERT INTO ms_library_sources(id, kind, display_name, path, resolved_path, owner_user_id,"
            " enabled, project_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, kind, display_name, path, resolved_path, owner_user_id or "", 1 if enabled else 0,
             project_id, _now()),
        )
        con.commit()
    finally:
        con.close()
    return sid


def list_sources() -> List[Dict[str, Any]]:
    con = _connect()
    try:
        return [_source_row(r) for r in con.execute(
            "SELECT * FROM ms_library_sources ORDER BY created_at ASC").fetchall()]
    finally:
        con.close()


def get_source(source_id: str) -> Optional[Dict[str, Any]]:
    con = _connect()
    try:
        row = con.execute("SELECT * FROM ms_library_sources WHERE id = ?", (source_id,)).fetchone()
        return _source_row(row) if row else None
    finally:
        con.close()


def update_source(source_id: str, *, counts: Any = None, **fields: Any) -> None:
    allowed = {"display_name", "enabled", "project_id", "last_scan_at", "last_success_at", "last_error"}
    sets, args = [], []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"not a source field: {key}")
        sets.append(f"{key} = ?")
        args.append(int(value) if key == "enabled" else value)
    if counts is not None:
        sets.append("counts_json = ?")
        args.append(_dumps(counts))
    if not sets:
        return
    con = _connect()
    try:
        con.execute(f"UPDATE ms_library_sources SET {', '.join(sets)} WHERE id = ?", args + [source_id])
        con.commit()
    finally:
        con.close()


def delete_source(source_id: str) -> None:
    """Disconnect a folder. Meetings imported from it stay — they are HomePilot's copies."""
    con = _connect()
    try:
        con.execute("DELETE FROM ms_library_sources WHERE id = ?", (source_id,))
        con.execute("DELETE FROM ms_library_sync_seen WHERE source_id = ?", (source_id,))
        con.commit()
    finally:
        con.close()


def observe(source_id: str, relative_path: str, size_bytes: int, mtime: float) -> Dict[str, Any]:
    """Record a file sighting. ``changed`` is True when it differs from the last sighting."""
    now = _now()
    con = _connect()
    try:
        row = con.execute(
            "SELECT * FROM ms_library_sync_seen WHERE source_id = ? AND relative_path = ?",
            (source_id, relative_path),
        ).fetchone()
        if row and int(row["size_bytes"]) == int(size_bytes) and float(row["mtime"]) == float(mtime):
            return {**dict(row), "changed": False}
        con.execute(
            "INSERT OR REPLACE INTO ms_library_sync_seen(source_id, relative_path, size_bytes, mtime, first_seen_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (source_id, relative_path, int(size_bytes), float(mtime), now),
        )
        con.commit()
        return {"source_id": source_id, "relative_path": relative_path, "size_bytes": size_bytes,
                "mtime": mtime, "first_seen_at": now, "changed": row is not None}
    finally:
        con.close()


# ── deletion helpers ────────────────────────────────────────────────────────


def delete_library_rows(meeting_id: str) -> Dict[str, int]:
    """Remove the library's rows for a meeting (MeetingSense removes its own)."""
    con = _connect()
    try:
        counts = {}
        for table, column in (
            ("ms_library_assets", "meeting_id"), ("ms_library_jobs", "meeting_id"),
            ("ms_meeting_project_links", "meeting_id"), ("ms_library_origin_links", "meeting_id"),
            ("ms_library_entries", "meeting_id"),
        ):
            cur = con.execute(f"DELETE FROM {table} WHERE {column} = ?", (meeting_id,))
            counts[table] = int(cur.rowcount or 0)
        vids = [r["id"] for r in con.execute(
            "SELECT id FROM ms_transcript_versions WHERE meeting_id = ?", (meeting_id,)).fetchall()]
        for vid in vids:
            con.execute("DELETE FROM ms_transcript_version_segments WHERE version_id = ?", (vid,))
        cur = con.execute("DELETE FROM ms_transcript_versions WHERE meeting_id = ?", (meeting_id,))
        counts["ms_transcript_versions"] = int(cur.rowcount or 0)
        con.commit()
        return counts
    finally:
        con.close()
