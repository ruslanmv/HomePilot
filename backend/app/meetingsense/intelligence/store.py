"""Persistence for analyses, visual specs and first-class action items.

Additive tables beside the library's, on the same connection (``store._connect``), created
only when the library migrates with ``MEETINGS_INTELLIGENCE`` on. Analyses are versioned
rows, never overwritten: regenerating keeps the previous page until the new one is ready,
and the history stays available.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence

from .. import store as ms_store
from .schema import MeetingAnalysis, SuggestedQuestion, VisualSpec

_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS ms_analyses(
        id                     TEXT PRIMARY KEY,
        meeting_id             TEXT NOT NULL,
        transcript_version_id  TEXT,
        schema_version         INTEGER NOT NULL,
        model                  TEXT,
        degraded               TEXT,
        status                 TEXT NOT NULL DEFAULT 'ready',
        json                   TEXT NOT NULL,
        report_json            TEXT,
        questions_json         TEXT,
        created_at             REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_visual_specs(
        id           TEXT PRIMARY KEY,
        analysis_id  TEXT NOT NULL,
        meeting_id   TEXT NOT NULL,
        template     TEXT NOT NULL,
        spec_json    TEXT NOT NULL,
        created_at   REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ms_action_items(
        id             TEXT PRIMARY KEY,
        meeting_id     TEXT NOT NULL,
        analysis_id    TEXT NOT NULL,
        item_id        TEXT NOT NULL,
        text           TEXT NOT NULL,
        owner          TEXT,
        due            TEXT,
        due_text       TEXT,
        status         TEXT NOT NULL DEFAULT 'open',
        evidence_json  TEXT,
        updated_at     REAL NOT NULL,
        UNIQUE(meeting_id, item_id)
    )
    """,
)
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_ms_analyses_meeting ON ms_analyses(meeting_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_ms_visual_specs_meeting ON ms_visual_specs(meeting_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_ms_action_items_meeting ON ms_action_items(meeting_id)",
)


def _connect():
    con = ms_store._connect()
    try:
        # WAL and a busy timeout: the worker, the live socket and request handlers all write
        # to this file. Best effort — a test's in-memory connection may refuse either.
        con.execute("PRAGMA busy_timeout = 5000")
    except Exception:  # noqa: BLE001
        pass
    return con


def migrate() -> None:
    con = _connect()
    try:
        cur = con.cursor()
        for statement in _TABLES:
            cur.execute(statement)
        for statement in _INDEXES:
            cur.execute(statement)
        con.commit()
    finally:
        con.close()


def _now() -> float:
    return time.time()


def save(meeting_id: str, analysis: MeetingAnalysis, spec: VisualSpec, questions: Sequence[SuggestedQuestion], *,
         transcript_version_id: Optional[str] = None) -> str:
    """One new analysis row, its spec, and the action items (statuses of items that already
    existed with the same text are carried over, so a tick survives regeneration)."""
    aid = uuid.uuid4().hex
    spec.analysis_id = aid
    now = _now()
    con = _connect()
    try:
        previous = {r["text"]: r for r in con.execute(
            "SELECT text, owner, due, status FROM ms_action_items WHERE meeting_id = ?", (meeting_id,)).fetchall()}
        con.execute(
            "INSERT INTO ms_analyses(id, meeting_id, transcript_version_id, schema_version, model, degraded, status,"
            " json, report_json, questions_json, created_at) VALUES (?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?)",
            (aid, meeting_id, transcript_version_id, analysis.schema_version, analysis.model, analysis.degraded,
             analysis.model_dump_json(), analysis.validator.model_dump_json() if analysis.validator else None,
             json.dumps([q.model_dump() for q in questions]), now),
        )
        con.execute(
            "INSERT INTO ms_visual_specs(id, analysis_id, meeting_id, template, spec_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, aid, meeting_id, spec.template, spec.model_dump_json(), now),
        )
        con.execute("DELETE FROM ms_action_items WHERE meeting_id = ?", (meeting_id,))
        for item in analysis.action_items:
            prior = previous.get(item.text)
            con.execute(
                "INSERT INTO ms_action_items(id, meeting_id, analysis_id, item_id, text, owner, due, due_text, status,"
                " evidence_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, meeting_id, aid, item.id, item.text,
                 (prior["owner"] if prior and prior["owner"] else item.owner),
                 (prior["due"] if prior and prior["due"] else item.due), item.due_text,
                 (prior["status"] if prior else item.status),
                 json.dumps([e.model_dump() for e in item.evidence]), now),
            )
        con.commit()
    finally:
        con.close()
    return aid


def save_spec(meeting_id: str, analysis_id: str, spec: VisualSpec) -> str:
    """A new visual spec for an existing analysis (re-layout). The previous spec stays."""
    spec.analysis_id = analysis_id
    sid = uuid.uuid4().hex
    con = _connect()
    try:
        con.execute(
            "INSERT INTO ms_visual_specs(id, analysis_id, meeting_id, template, spec_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (sid, analysis_id, meeting_id, spec.template, spec.model_dump_json(), _now()),
        )
        con.commit()
    finally:
        con.close()
    return sid


def latest(meeting_id: str) -> Optional[Dict[str, Any]]:
    """The newest analysis with its spec and questions, as plain dicts, or ``None``."""
    con = _connect()
    try:
        row = con.execute("SELECT * FROM ms_analyses WHERE meeting_id = ? AND status = 'ready' ORDER BY created_at DESC LIMIT 1",
                          (meeting_id,)).fetchone()
        if row is None:
            return None
        spec = con.execute("SELECT spec_json FROM ms_visual_specs WHERE analysis_id = ? ORDER BY created_at DESC LIMIT 1",
                           (row["id"],)).fetchone()
        count = con.execute("SELECT COUNT(*) AS n FROM ms_analyses WHERE meeting_id = ?", (meeting_id,)).fetchone()
        return {
            "id": row["id"], "meeting_id": meeting_id, "created_at": row["created_at"], "model": row["model"],
            "degraded": row["degraded"], "schema_version": row["schema_version"],
            "transcript_version_id": row["transcript_version_id"],
            "analysis": json.loads(row["json"]),
            "report": json.loads(row["report_json"]) if row["report_json"] else None,
            "questions": json.loads(row["questions_json"]) if row["questions_json"] else [],
            "visual": json.loads(spec["spec_json"]) if spec else None,
            "versions": int(count["n"]) if count else 1,
        }
    finally:
        con.close()


def _action_row(row) -> Dict[str, Any]:
    out = dict(row)
    raw = out.pop("evidence_json", None)
    try:
        out["evidence"] = json.loads(raw) if raw else []
    except ValueError:
        out["evidence"] = []
    return out


def actions(meeting_id: str) -> List[Dict[str, Any]]:
    con = _connect()
    try:
        return [_action_row(r) for r in con.execute(
            "SELECT * FROM ms_action_items WHERE meeting_id = ? ORDER BY updated_at ASC", (meeting_id,)).fetchall()]
    finally:
        con.close()


UPDATABLE = ("status", "owner", "due", "text")


def update_action(meeting_id: str, item_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    sets, args = [], []
    for key in UPDATABLE:
        if key in fields and fields[key] is not None:
            value = str(fields[key]).strip()
            if key == "status" and value not in ("open", "done", "dropped"):
                continue
            sets.append(f"{key} = ?")
            args.append(value or None)
    con = _connect()
    try:
        if sets:
            sets.append("updated_at = ?")
            args.append(_now())
            con.execute(f"UPDATE ms_action_items SET {', '.join(sets)} WHERE meeting_id = ? AND item_id = ?",
                        args + [meeting_id, item_id])
            con.commit()
        row = con.execute("SELECT * FROM ms_action_items WHERE meeting_id = ? AND item_id = ?", (meeting_id, item_id)).fetchone()
        return _action_row(row) if row else None
    finally:
        con.close()


def delete_for(meeting_id: str) -> Dict[str, int]:
    con = _connect()
    try:
        out = {}
        for table in ("ms_action_items", "ms_visual_specs", "ms_analyses"):
            out[table] = con.execute(f"DELETE FROM {table} WHERE meeting_id = ?", (meeting_id,)).rowcount
        con.commit()
        return out
    finally:
        con.close()
