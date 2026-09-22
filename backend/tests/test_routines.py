from __future__ import annotations

from pathlib import Path

from app.routines import store


def test_routines_are_user_scoped_and_soft_deleted(tmp_path: Path, monkeypatch):
    db = tmp_path / "routines.sqlite"
    monkeypatch.setattr(store, "_db_path", lambda: str(db))

    first = store.create_routine(
        "user-a",
        {
            "name": "Morning news",
            "enabled": True,
            "timezone": "Europe/Rome",
            "schedule": {"type": "daily", "time": "08:00", "days": []},
            "action": {"type": "news_digest", "parameters": {"max_items": 6}},
            "delivery": {"in_app": True, "speak_if_active": True, "catch_up": True},
        },
    )
    store.create_routine(
        "user-b",
        {
            "name": "Other user's routine",
            "enabled": True,
            "timezone": "UTC",
            "schedule": {"type": "daily", "time": "09:00", "days": []},
            "action": {"type": "reminder", "parameters": {"message": "Hello"}},
            "delivery": {"in_app": True, "speak_if_active": False, "catch_up": False},
        },
    )

    assert [r["id"] for r in store.list_routines("user-a")] == [first["id"]]
    assert store.get_routine("user-b", first["id"]) is None

    updated = store.update_routine("user-a", first["id"], {"enabled": False, "name": "News later"})
    assert updated is not None
    assert updated["enabled"] is False
    assert updated["name"] == "News later"

    assert store.archive_routine("user-a", first["id"]) is True
    assert store.list_routines("user-a") == []
    assert store.get_routine("user-a", first["id"]) is None


def test_archiving_someone_elses_routine_is_a_noop(tmp_path: Path, monkeypatch):
    db = tmp_path / "routines.sqlite"
    monkeypatch.setattr(store, "_db_path", lambda: str(db))

    routine = store.create_routine(
        "owner",
        {
            "name": "Private routine",
            "enabled": True,
            "timezone": "UTC",
            "schedule": {"type": "weekly", "time": "18:30", "days": [1, 3, 5]},
            "action": {"type": "assistant_prompt", "parameters": {"prompt": "Summarize today"}},
            "delivery": {"in_app": True, "speak_if_active": True, "catch_up": True},
        },
    )

    assert store.archive_routine("other-user", routine["id"]) is False
    assert store.get_routine("owner", routine["id"]) is not None
