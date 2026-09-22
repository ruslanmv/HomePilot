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
