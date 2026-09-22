from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.routines import actions, scheduler, service, store


def _routine(**overrides):
    data = {
        "id": "routine-1",
        "name": "Morning news",
        "enabled": True,
        "timezone": "Europe/Rome",
        "created_at": "2026-09-01T00:00:00+00:00",
        "schedule": {"type": "daily", "time": "05:43"},
        "target": {"type": "assistant"},
        "action": {
            "type": "assistant_prompt",
            "parameters": {"prompt": "Summarize my priorities."},
        },
        "delivery": {
            "in_app": True,
            "notification": True,
            "create_conversation": True,
            "speak_if_active": True,
            "catch_up": True,
        },
    }
    data.update(overrides)
    return data


def test_daily_schedule_tracks_europe_rome_dst():
    before = scheduler.most_recent_occurrence(
        _routine(),
        datetime(2026, 10, 24, 8, 0, tzinfo=timezone.utc),
    )
    after = scheduler.most_recent_occurrence(
        _routine(),
        datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc),
    )

    assert before == datetime(2026, 10, 24, 3, 43, tzinfo=timezone.utc)
    assert after == datetime(2026, 10, 26, 4, 43, tzinfo=timezone.utc)


def test_weekly_schedule_finds_previous_enabled_day():
    routine = _routine(
        schedule={"type": "weekly", "time": "07:30", "days": [1, 3, 5]},
    )
    occurrence = scheduler.most_recent_occurrence(
        routine,
        datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc),  # Tuesday
    )
    assert occurrence == datetime(2026, 9, 21, 5, 30, tzinfo=timezone.utc)


def test_scheduler_marks_stale_non_catchup_run_missed(tmp_path: Path, monkeypatch):
    db = tmp_path / "routines.sqlite"
    monkeypatch.setattr(store, "_db_path", lambda: str(db))
    monkeypatch.setenv("ROUTINES_EXECUTION_ENABLED", "true")

    routine = store.create_routine(
        "user-a",
        {
            "name": "Leave reminder",
            "enabled": True,
            "timezone": "Europe/Rome",
            "schedule": {"type": "daily", "time": "05:43"},
            "target": {"type": "assistant"},
            "action": {"type": "reminder", "parameters": {"message": "Leave now"}},
            "delivery": {
                "in_app": True,
                "notification": True,
                "create_conversation": True,
                "speak_if_active": False,
                "catch_up": False,
            },
        },
    )
    con = sqlite3.connect(db)
    con.execute(
        "UPDATE user_routines SET created_at = ? WHERE id = ?",
        ("2026-09-01T00:00:00+00:00", routine["id"]),
    )
    con.commit()
    con.close()

    stats = asyncio.run(
        scheduler.tick(datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc))
    )
    assert stats["missed"] == 1
    runs = store.list_runs("user-a", routine_id=routine["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "missed"


def test_run_now_creates_native_conversation_and_presentation(tmp_path: Path, monkeypatch):
    db = tmp_path / "routines.sqlite"
    monkeypatch.setattr(store, "_db_path", lambda: str(db))

    async def fake_prepare(_routine):
        return {
            "message": "Prepare my morning news briefing for today.",
            "extra_context": "trusted fresh context",
            "sources": [{"name": "Example", "url": "https://example.test/story"}],
            "provider": "hp-news",
        }

    async def fake_handle(mode, payload):
        assert mode == "chat"
        assert payload["extra_system_context"] == "trusted fresh context"
        return {
            "conversation_id": payload["conversation_id"],
            "text": "## Good morning\n\nHere is your briefing.",
            "media": None,
        }

    monkeypatch.setattr(service.actions, "prepare_action", fake_prepare)
    monkeypatch.setattr(service, "handle_request", fake_handle)

    routine = store.create_routine(
        "user-a",
        {
            **_routine(),
            "action": {"type": "news_digest", "parameters": {"max_items": 6}},
        },
    )
    run = asyncio.run(service.run_now("user-a", routine))

    assert run["status"] == "success"
    assert run["conversation_id"]
    assert run["result"]["provider"] == "hp-news"
    assert run["result"]["presentation"]["speech_text"] == "Good morning Here is your briefing."
    assert run["result"]["presentation"]["sources"][0]["url"] == "https://example.test/story"


def test_persona_target_allocates_fresh_session(monkeypatch):
    calls = {}

    def fake_create(project_id, mode, title, force_new):
        calls.update(
            project_id=project_id,
            mode=mode,
            title=title,
            force_new=force_new,
        )
        return {"conversation_id": "persona-conversation"}

    monkeypatch.setattr(service.persona_sessions, "create_session", fake_create)
    conversation_id, project_id, mode = service._conversation_for_target(
        _routine(target={"type": "persona", "project_id": "sofia"}),
        scheduled_for="2026-09-22T03:43:00+00:00",
    )

    assert conversation_id == "persona-conversation"
    assert project_id == "sofia"
    assert mode == "project"
    assert calls["force_new"] is True
    assert calls["title"].startswith("Morning news ·")


def test_news_prefers_hp_news_then_falls_back_to_web(monkeypatch):
    class DummyClient:
        async def invoke_tool(self, tool_id, args, timeout=30.0):
            if tool_id == "news.top":
                return {"error": "not installed"}
            assert tool_id == "hp.web.search"
            return {
                "results": [
                    {
                        "title": "Local headline",
                        "url": "https://example.test/local",
                    }
                ]
            }

    monkeypatch.setattr(actions, "_forge_client", lambda: DummyClient())
    material = asyncio.run(
        actions.prepare_action(
            _routine(
                action={
                    "type": "news_digest",
                    "parameters": {"max_items": 4, "scope": ["local", "world"]},
                }
            )
        )
    )

    assert material["provider"] == "hp.web.search"
    assert material["message"] == "Prepare my morning news briefing for today."
    assert "CURRENT INFORMATION" in material["extra_context"]
    assert material["sources"][0]["url"] == "https://example.test/local"
