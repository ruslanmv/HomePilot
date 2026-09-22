from __future__ import annotations

import sqlite3
from pathlib import Path

from app.routines import store


def _routine(name: str = "Morning news") -> dict:
    return {
        "name": name,
        "enabled": True,
        "timezone": "Europe/Rome",
        "schedule": {"type": "daily", "time": "08:00", "days": []},
        "target": {"type": "assistant"},
        "action": {"type": "news_digest", "parameters": {"max_items": 6}},
        "delivery": {
            "in_app": True,
            "notification": True,
            "create_conversation": True,
            "speak_if_active": True,
            "catch_up": True,
        },
    }


def test_routines_are_user_scoped_and_soft_deleted(tmp_path: Path, monkeypatch):
    db = tmp_path / "routines.sqlite"
    monkeypatch.setattr(store, "_db_path", lambda: str(db))

    first = store.create_routine("user-a", _routine())
    store.create_routine(
        "user-b",
        {
            **_routine("Other user's routine"),
            "timezone": "UTC",
            "action": {"type": "reminder", "parameters": {"message": "Hello"}},
        },
    )

    assert [r["id"] for r in store.list_routines("user-a")] == [first["id"]]
    assert store.get_routine("user-b", first["id"]) is None

    updated = store.update_routine(
        "user-a",
        first["id"],
        {
            "enabled": False,
            "name": "News later",
            "target": {"type": "persona", "project_id": "persona-123"},
        },
    )
    assert updated is not None
    assert updated["enabled"] is False
    assert updated["name"] == "News later"
    assert updated["target"] == {"type": "persona", "project_id": "persona-123"}

    assert store.archive_routine("user-a", first["id"]) is True
    assert store.list_routines("user-a") == []
    assert store.get_routine("user-a", first["id"]) is None


def test_archiving_someone_elses_routine_is_a_noop(tmp_path: Path, monkeypatch):
    db = tmp_path / "routines.sqlite"
    monkeypatch.setattr(store, "_db_path", lambda: str(db))

    routine = store.create_routine(
        "owner",
        {
            **_routine("Private routine"),
            "timezone": "UTC",
            "schedule": {"type": "weekly", "time": "18:30", "days": [1, 3, 5]},
            "action": {"type": "assistant_prompt", "parameters": {"prompt": "Summarize today"}},
        },
    )

    assert store.archive_routine("other-user", routine["id"]) is False
    assert store.get_routine("owner", routine["id"]) is not None


def test_v1_schema_is_migrated_without_losing_routines(tmp_path: Path, monkeypatch):
    db = tmp_path / "routines.sqlite"
    monkeypatch.setattr(store, "_db_path", lambda: str(db))

    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE user_routines(
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            timezone TEXT NOT NULL DEFAULT 'UTC',
            schedule_json TEXT NOT NULL DEFAULT '{}',
            action_json TEXT NOT NULL DEFAULT '{}',
            delivery_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT
        )
        """
    )
    con.execute(
        """
        INSERT INTO user_routines(
            id, user_id, name, enabled, timezone,
            schedule_json, action_json, delivery_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-routine",
            "legacy-user",
            "Legacy morning news",
            1,
            "Europe/Rome",
            '{"type":"daily","time":"05:43"}',
            '{"type":"news_digest","parameters":{}}',
            '{"in_app":true,"speak_if_active":true,"catch_up":true}',
            "2026-09-22T00:00:00+00:00",
            "2026-09-22T00:00:00+00:00",
        ),
    )
    con.commit()
    con.close()

    rows = store.list_routines("legacy-user")
    assert len(rows) == 1
    assert rows[0]["id"] == "legacy-routine"
    assert rows[0]["target"] == {"type": "assistant"}
    assert rows[0]["delivery"]["notification"] is True
    assert rows[0]["delivery"]["create_conversation"] is True



def test_run_claims_are_idempotent_and_user_scoped(tmp_path: Path, monkeypatch):
    db = tmp_path / "routines.sqlite"
    monkeypatch.setattr(store, "_db_path", lambda: str(db))

    routine = store.create_routine("owner", _routine())
    scheduled_for = "2026-09-22T05:43:00+02:00"
    run_key = f"{routine['id']}:{scheduled_for}"

    first, created_first = store.claim_run(
        "owner",
        routine["id"],
        scheduled_for=scheduled_for,
        run_key=run_key,
    )
    second, created_second = store.claim_run(
        "owner",
        routine["id"],
        scheduled_for=scheduled_for,
        run_key=run_key,
    )

    assert created_first is True
    assert created_second is False
    assert first["id"] == second["id"]
    assert store.get_run("other-user", first["id"]) is None

    finished = store.finish_run(
        "owner",
        first["id"],
        status="success",
        conversation_id="conversation-123",
        result_preview="Morning briefing ready",
        result={"speech_text": "Good morning"},
    )
    assert finished is not None
    assert finished["status"] == "success"
    assert finished["conversation_id"] == "conversation-123"

    unseen = store.list_runs("owner", unseen_only=True)
    assert [item["id"] for item in unseen] == [first["id"]]

    opened = store.mark_run_seen("owner", first["id"], opened=True)
    assert opened is not None
    assert opened["seen_at"]
    assert opened["opened_at"]
    assert store.list_runs("owner", unseen_only=True) == []
