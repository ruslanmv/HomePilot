"""SQLite persistence for HomePilot routines.

Design rules:
- additive schema only
- every row is scoped by user_id
- delete is soft-delete (archived_at), so UI can add Undo later
- schedule/target/action/delivery stay JSON objects to keep the public contract
  extensible without schema churn
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _db_path() -> str:
    from ..storage import _get_db_path
    return _get_db_path()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_schema() -> None:
    con = sqlite3.connect(_db_path())
    try:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_routines(
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                timezone TEXT NOT NULL DEFAULT 'UTC',
                schedule_json TEXT NOT NULL DEFAULT '{}',
                target_json TEXT NOT NULL DEFAULT '{"type":"assistant"}',
                action_json TEXT NOT NULL DEFAULT '{}',
                delivery_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived_at TEXT
            )
            """
        )
        # Existing v1 installs predate target_json. Add it in-place without
        # rewriting or deleting any routine definitions.
        if "target_json" not in _columns(con, "user_routines"):
            cur.execute(
                """ALTER TABLE user_routines
                   ADD COLUMN target_json TEXT NOT NULL
                   DEFAULT '{"type":"assistant"}'"""
            )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_routines_owner "
            "ON user_routines(user_id, archived_at, updated_at)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS routine_runs(
                id TEXT PRIMARY KEY,
                routine_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                run_key TEXT NOT NULL UNIQUE,
                scheduled_for TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                status TEXT NOT NULL,
                project_id TEXT,
                conversation_id TEXT,
                result_preview TEXT,
                result_json TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                seen_at TEXT,
                opened_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_routine_runs_owner "
            "ON routine_runs(user_id, routine_id, created_at DESC)"
        )
        con.commit()
    finally:
        con.close()


def _load_object(value: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _decode(row: sqlite3.Row) -> Dict[str, Any]:
    target = {"type": "assistant"}
    target.update(_load_object(row["target_json"]))

    delivery = {
        "in_app": True,
        "notification": True,
        "create_conversation": True,
        "speak_if_active": True,
        "catch_up": True,
    }
    delivery.update(_load_object(row["delivery_json"]))

    return {
        "id": row["id"],
        "name": row["name"],
        "enabled": bool(row["enabled"]),
        "timezone": row["timezone"],
        "schedule": _load_object(row["schedule_json"]),
        "target": target,
        "action": _load_object(row["action_json"]),
        "delivery": delivery,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_routines(user_id: str) -> List[Dict[str, Any]]:
    ensure_schema()
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT * FROM user_routines
            WHERE user_id = ? AND archived_at IS NULL
            ORDER BY enabled DESC, updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [_decode(row) for row in rows]
    finally:
        con.close()


def list_enabled_routines_with_owner() -> List[Dict[str, Any]]:
    """Return active routine definitions for the background scheduler."""
    ensure_schema()
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT * FROM user_routines
            WHERE enabled = 1 AND archived_at IS NULL
            ORDER BY updated_at ASC
            """
        ).fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            routine = _decode(row)
            routine["user_id"] = row["user_id"]
            result.append(routine)
        return result
    finally:
        con.close()


def get_routine(user_id: str, routine_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            """
            SELECT * FROM user_routines
            WHERE id = ? AND user_id = ? AND archived_at IS NULL
            """,
            (routine_id, user_id),
        ).fetchone()
        return _decode(row) if row else None
    finally:
        con.close()


def create_routine(user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema()
    routine_id = str(uuid.uuid4())
    now = _now()
    con = sqlite3.connect(_db_path())
    try:
        con.execute(
            """
            INSERT INTO user_routines(
                id, user_id, name, enabled, timezone,
                schedule_json, target_json, action_json, delivery_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                routine_id,
                user_id,
                data["name"].strip(),
                1 if data.get("enabled", True) else 0,
                data.get("timezone") or "UTC",
                json.dumps(data.get("schedule") or {}, ensure_ascii=False),
                json.dumps(data.get("target") or {"type": "assistant"}, ensure_ascii=False),
                json.dumps(data.get("action") or {}, ensure_ascii=False),
                json.dumps(data.get("delivery") or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
        con.commit()
    finally:
        con.close()
    return get_routine(user_id, routine_id)  # type: ignore[return-value]


def update_routine(user_id: str, routine_id: str, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    current = get_routine(user_id, routine_id)
    if not current:
        return None

    allowed = {
        "name": "name",
        "enabled": "enabled",
        "timezone": "timezone",
        "schedule": "schedule_json",
        "target": "target_json",
        "action": "action_json",
        "delivery": "delivery_json",
    }
    sets: List[str] = []
    values: List[Any] = []
    for key, column in allowed.items():
        if key not in changes:
            continue
        value = changes[key]
        if key == "name":
            value = str(value).strip()
        elif key == "enabled":
            value = 1 if value else 0
        elif key in {"schedule", "target", "action", "delivery"}:
            value = json.dumps(value or {}, ensure_ascii=False)
        sets.append(f"{column} = ?")
        values.append(value)

    if not sets:
        return current

    sets.append("updated_at = ?")
    values.append(_now())
    values.extend([routine_id, user_id])

    con = sqlite3.connect(_db_path())
    try:
        con.execute(
            f"UPDATE user_routines SET {', '.join(sets)} "
            "WHERE id = ? AND user_id = ? AND archived_at IS NULL",
            values,
        )
        con.commit()
    finally:
        con.close()
    return get_routine(user_id, routine_id)


def archive_routine(user_id: str, routine_id: str) -> bool:
    ensure_schema()
    now = _now()
    con = sqlite3.connect(_db_path())
    try:
        cur = con.execute(
            """
            UPDATE user_routines
            SET archived_at = ?, updated_at = ?
            WHERE id = ? AND user_id = ? AND archived_at IS NULL
            """,
            (now, now, routine_id, user_id),
        )
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()



def _decode_run(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "routine_id": row["routine_id"],
        "run_key": row["run_key"],
        "scheduled_for": row["scheduled_for"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "status": row["status"],
        "project_id": row["project_id"],
        "conversation_id": row["conversation_id"],
        "result_preview": row["result_preview"],
        "result": _load_object(row["result_json"]),
        "error": row["error"],
        "seen_at": row["seen_at"],
        "opened_at": row["opened_at"],
        "created_at": row["created_at"],
    }


def get_run(user_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT * FROM routine_runs WHERE id = ? AND user_id = ?",
            (run_id, user_id),
        ).fetchone()
        return _decode_run(row) if row else None
    finally:
        con.close()


def get_run_by_key(user_id: str, run_key: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT * FROM routine_runs WHERE run_key = ? AND user_id = ?",
            (run_key, user_id),
        ).fetchone()
        return _decode_run(row) if row else None
    finally:
        con.close()


def claim_run(
    user_id: str,
    routine_id: str,
    *,
    scheduled_for: str,
    run_key: Optional[str] = None,
) -> tuple[Dict[str, Any], bool]:
    """Atomically claim an execution slot.

    Returns (run, created). A duplicate run_key returns the original run with
    created=False, which makes scheduler retries and multi-worker ticks safe.
    """
    ensure_schema()
    key = run_key or f"{routine_id}:{scheduled_for}"
    run_id = str(uuid.uuid4())
    now = _now()
    con = sqlite3.connect(_db_path())
    try:
        cur = con.execute(
            """
            INSERT OR IGNORE INTO routine_runs(
                id, routine_id, user_id, run_key, scheduled_for,
                started_at, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)
            """,
            (run_id, routine_id, user_id, key, scheduled_for, now, now),
        )
        con.commit()
        created = cur.rowcount > 0
    finally:
        con.close()

    run = get_run(user_id, run_id) if created else get_run_by_key(user_id, key)
    if not run:
        raise RuntimeError("Could not load claimed routine run")
    return run, created


def finish_run(
    user_id: str,
    run_id: str,
    *,
    status: str,
    project_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    result_preview: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    ensure_schema()
    con = sqlite3.connect(_db_path())
    try:
        con.execute(
            """
            UPDATE routine_runs
            SET completed_at = ?, status = ?, project_id = ?,
                conversation_id = ?, result_preview = ?, result_json = ?, error = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                _now(),
                status,
                project_id,
                conversation_id,
                result_preview,
                json.dumps(result or {}, ensure_ascii=False),
                error,
                run_id,
                user_id,
            ),
        )
        con.commit()
    finally:
        con.close()
    return get_run(user_id, run_id)


def list_runs(
    user_id: str,
    *,
    routine_id: Optional[str] = None,
    limit: int = 50,
    unseen_only: bool = False,
) -> List[Dict[str, Any]]:
    ensure_schema()
    clauses = ["user_id = ?"]
    params: List[Any] = [user_id]
    if routine_id:
        clauses.append("routine_id = ?")
        params.append(routine_id)
    if unseen_only:
        clauses.append("seen_at IS NULL")
        clauses.append("status = 'success'")
    params.append(max(1, min(int(limit), 200)))

    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"SELECT * FROM routine_runs WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_decode_run(row) for row in rows]
    finally:
        con.close()


def mark_run_seen(user_id: str, run_id: str, *, opened: bool = False) -> Optional[Dict[str, Any]]:
    ensure_schema()
    now = _now()
    con = sqlite3.connect(_db_path())
    try:
        if opened:
            con.execute(
                """
                UPDATE routine_runs
                SET seen_at = COALESCE(seen_at, ?), opened_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (now, now, run_id, user_id),
            )
        else:
            con.execute(
                """
                UPDATE routine_runs
                SET seen_at = COALESCE(seen_at, ?)
                WHERE id = ? AND user_id = ?
                """,
                (now, run_id, user_id),
            )
        con.commit()
    finally:
        con.close()
    return get_run(user_id, run_id)
