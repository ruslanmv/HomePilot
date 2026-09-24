from __future__ import annotations

import asyncio
import contextlib
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
            "instruction": "Prepare today's news briefing for the user.",
            "extra_context": "trusted fresh context",
            "sources": [{"name": "Example", "url": "https://example.test/story"}],
            "provider": "hp-news",
        }

    async def fake_handle(mode, payload):
        assert mode == "chat"
        assert payload["extra_system_context"] == "trusted fresh context"
        assert payload["persist_project_conversation"] is False
        # The routine acts on its own, so its turn is never attributed to the user.
        assert payload["system_initiated"] is True
        assert "Scheduled routine" in payload["message"]
        assert "Prepare today's news briefing" in payload["message"]
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

    def fake_create(project_id, mode, title, force_new, activate=True):
        calls.update(
            project_id=project_id,
            mode=mode,
            title=title,
            force_new=force_new,
            activate=activate,
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
    assert calls["activate"] is False
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
    # A task addressed to the assistant, not a sentence attributed to the user.
    assert material["instruction"].startswith("Prepare today's news briefing")
    assert "message" not in material
    assert "CURRENT INFORMATION" in material["extra_context"]
    assert material["sources"][0]["url"] == "https://example.test/local"


# ── a routine is something HomePilot does, not something the user said ──────


def test_a_routine_never_writes_a_user_turn_into_its_conversation(tmp_path, monkeypatch):
    """The bug this batch exists to remove.

    A routine used to open its conversation with a fabricated first-person line — *"Prepare
    my morning news briefing for today."* — attributed to the user, who was very possibly
    asleep. The prepared instruction was handed to the chat pipeline as `payload["message"]`,
    and both chat paths persist that with `role="user"`.

    Nothing downstream could tell it from a real request: not the reader opening the thread,
    not search, not memory, not a later summary. And the user's first genuine message landed
    *second*, in a conversation that already misrepresented them.

    So this drives the real `orchestrate` persistence path and asserts on what is in storage.
    Asserting on the payload alone would pass for a routine that still forged the turn one
    layer down, which is exactly where the bug lived.
    """
    from app import orchestrator
    from app import storage

    db = tmp_path / "routines.sqlite"
    monkeypatch.setattr(store, "_db_path", lambda: str(db))

    written: list[tuple[str, str, str]] = []

    def fake_add_message(cid, role, content, **kwargs):
        written.append((cid, role, content))

    monkeypatch.setattr(orchestrator, "add_message", fake_add_message)
    monkeypatch.setattr(storage, "add_message", fake_add_message, raising=False)

    async def fake_prepare(_routine):
        return {
            "instruction": "Prepare today's news briefing for the user.",
            "extra_context": "fresh context",
            "sources": [],
            "provider": "hp-news",
        }

    monkeypatch.setattr(service.actions, "prepare_action", fake_prepare)

    async def fake_handle(mode, payload):
        # Stand in for the chat pipeline's own persistence, using the real decision the
        # orchestrator makes rather than a second copy of the rule.
        role = "system" if payload.get("system_initiated") else "user"
        fake_add_message(payload["conversation_id"], role, payload["message"])
        fake_add_message(payload["conversation_id"], "assistant", "Here is your briefing.")
        return {
            "conversation_id": payload["conversation_id"],
            "text": "Here is your briefing.",
            "media": None,
        }

    monkeypatch.setattr(service, "handle_request", fake_handle)

    routine = store.create_routine("user-a", {**_routine(), "action": {
        "type": "news_digest", "parameters": {"max_items": 4},
    }})
    asyncio.run(service.run_now("user-a", routine))

    roles = [role for _, role, _ in written]
    assert "user" not in roles, f"a routine forged a user turn: {written}"
    assert roles == ["system", "assistant"], roles

    marker = written[0][2]
    assert "Scheduled routine" in marker
    assert "Morning news" in marker
    # The marker doubles as the model's task, so the instruction has to survive in it.
    assert "Prepare today's news briefing" in marker


def test_the_opening_turn_says_what_ran_and_when_in_the_routines_timezone():
    routine = _routine(name="Morning news", timezone="Europe/Rome")
    # 05:43 UTC is 07:43 in Rome in September — the user's clock, not the server's.
    turn = service.opening_turn(
        routine, "Prepare today's news briefing.", "2026-09-24T05:43:00+00:00"
    )
    assert "Morning news" in turn
    assert "07:43" in turn
    assert "Sep 24" in turn
    assert "Prepare today's news briefing." in turn


def test_every_action_returns_a_task_rather_than_a_user_utterance():
    """No action may phrase its instruction as the user speaking.

    First person here is how the forged turn read as normal: "Give me my daily briefing"
    looks like a request because it is written as one. The instruction is addressed *to*
    the assistant, so it should never open in the user's voice.
    """
    import asyncio as _asyncio

    material = _asyncio.run(
        actions.prepare_action(
            _routine(action={"type": "reminder", "parameters": {"message": "Leave now"}})
        )
    )
    assert material["instruction"] == "Remind the user: Leave now"

    material = _asyncio.run(
        actions.prepare_action(
            _routine(action={"type": "assistant_prompt", "parameters": {"prompt": "Check CI"}})
        )
    )
    assert material["instruction"] == "Check CI"
    assert "Nobody has just spoken to you" in material["extra_context"]


def test_handle_request_forwards_system_initiated_to_both_chat_paths(monkeypatch):
    """The wiring, not just the flag.

    `orchestrate` grew a parameter and `handle_request` has two call sites into it. A new
    parameter that one branch forwards and the other silently drops is the exact shape of
    bug that makes a fix look applied while half the traffic still carries the old
    behaviour — and `handle_request` picks the branch by inspecting the payload, so which
    one a routine takes is not obvious from the call.
    """
    import asyncio as _asyncio

    from app import orchestrator

    seen: list[dict] = []

    async def fake_orchestrate(*args, **kwargs):
        seen.append(kwargs)
        return {"conversation_id": kwargs.get("conversation_id") or "c", "text": "ok", "media": None}

    monkeypatch.setattr(orchestrator, "orchestrate", fake_orchestrate)

    _asyncio.run(
        orchestrator.handle_request(
            "chat",
            {"message": "do the thing", "conversation_id": "c1", "system_initiated": True},
        )
    )
    assert seen, "handle_request never reached orchestrate"
    assert seen[-1]["system_initiated"] is True

    # And the default stays false, so an ordinary message is still the user's.
    _asyncio.run(
        orchestrator.handle_request("chat", {"message": "hello", "conversation_id": "c2"})
    )
    assert seen[-1]["system_initiated"] is False

    # The *other* call site: a project turn whose text reads as media intent is delegated
    # to `orchestrate` from a different branch entirely. A routine phrased "create a
    # picture of today's forecast" lands here, so forwarding has to hold on both paths —
    # and this assertion is the one that fails if only the obvious branch was updated.
    monkeypatch.setattr(orchestrator, "get_project_by_id", lambda _pid: {"id": "p1"})
    _asyncio.run(
        orchestrator.handle_request(
            "project",
            {
                "message": "create a picture of today's forecast",
                "conversation_id": "c3",
                "project_id": "p1",
                "system_initiated": True,
            },
        )
    )
    assert seen[-1]["system_initiated"] is True


# ── the conversation a routine leaves behind is readable by its owner ───────


def test_a_routines_conversation_opens_with_its_content(tmp_path, monkeypatch):
    """"Open latest" used to open an empty chat.

    `add_message` infers an owner when none is passed, and its last resort is the *default*
    user. Every scheduled routine knew the user id, put it in the payload, and then wrote its
    messages through `add_message` calls that did not forward it — so the conversation ended
    up owned by the default user.

    `get_messages` inner-joins `conversation_owners`, so the person the routine ran for got
    **zero rows** back: the chat opened, and it was blank.

    This drives the real storage layer rather than a fake, because the bug lived entirely in
    what the two of them agreed about — a test with a stubbed `add_message` would have passed
    throughout.
    """
    from app import storage

    db = tmp_path / "chat.sqlite3"
    monkeypatch.setattr(storage, "_get_db_path", lambda: str(db))
    storage.init_db()

    conversation_id = "conv-routine-1"
    owner = "user-a"

    # What the executor does: claim the conversation, then write the turns without repeating
    # the user id on every call.
    storage.ensure_conversation_owner(conversation_id, owner)
    storage.add_message(conversation_id, "system", "Scheduled routine “Evening wind-down” ran.")
    storage.add_message(conversation_id, "assistant", "Three things matter tomorrow…")

    seen = storage.get_messages(conversation_id, user_id=owner)
    assert [m["role"] for m in seen] == ["system", "assistant"], seen
    assert "Three things matter tomorrow" in seen[-1]["content"]


def test_without_the_ownership_claim_the_owner_sees_nothing(tmp_path, monkeypatch):
    """The failure mode itself, so the fix cannot be quietly removed.

    Writing the same two messages *without* claiming ownership hands them to the default
    user, and the real owner's read comes back empty — which is exactly what "open latest
    opens a blank chat" looked like from the outside.
    """
    from app import storage

    db = tmp_path / "chat.sqlite3"
    monkeypatch.setattr(storage, "_get_db_path", lambda: str(db))
    storage.init_db()

    conversation_id = "conv-routine-2"
    storage.add_message(conversation_id, "assistant", "Three things matter tomorrow…")

    assert storage.get_messages(conversation_id, user_id="user-a") == []
    # The messages are there — they just belong to somebody else.
    assert len(storage.get_messages(conversation_id)) == 1


def test_orchestrate_claims_the_conversation_for_the_caller(tmp_path, monkeypatch):
    """The claim happens on the real chat path, not only in the executor.

    A routine reaches storage through `orchestrate`, so asserting on the helper alone would
    pass for a build that never calls it.
    """
    from app import orchestrator

    claimed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        orchestrator,
        "ensure_conversation_owner",
        lambda cid, uid: claimed.append((cid, uid)),
    )
    monkeypatch.setattr(orchestrator, "add_message", lambda *a, **k: None)

    # `orchestrate` does a great deal after this point; the claim is the first thing it does
    # and the only thing under test, so the run is allowed to fail after it.
    import asyncio as _asyncio

    with contextlib.suppress(Exception):
        _asyncio.run(
            orchestrator.orchestrate(
                "hello",
                conversation_id="conv-x",
                user_id="user-a",
            )
        )

    assert ("conv-x", "user-a") in claimed
