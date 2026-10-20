"""Meetings a previous server process left open are closed at startup.

Regression: the backend restarted (an auto-reload) one second after a meeting started. The
row stayed ``suspended`` forever — sessions live in memory, so nothing could resume it — and
earlier meetings from the same day were still ``live`` hours later.
"""
import importlib
import sqlite3

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    module = importlib.import_module("app.meetingsense.store")
    db = tmp_path / "meetings.sqlite3"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(module, "_connect", _connect)
    module.migrate()
    return module


def test_live_and_suspended_meetings_are_ended_with_a_truthful_time(store):
    store.create_meeting(conversation_id="c1", meeting_id="live-with-lines", started_at=1000.0)
    store.add_segments("live-with-lines", [
        {"t0_ms": 0, "t1_ms": 4000, "speaker": "me", "text": "hello"},
        {"t0_ms": 5000, "t1_ms": 9500, "speaker": "them", "text": "hi there"},
    ])
    store.create_meeting(conversation_id="c1", meeting_id="suspended", started_at=2000.0)
    store.suspend_meeting("suspended", suspended_at=2060.0)
    store.create_meeting(conversation_id="c1", meeting_id="empty", started_at=3000.0)
    store.create_meeting(conversation_id="c1", meeting_id="finished", started_at=4000.0)
    store.end_meeting("finished", ended_at=4100.0)

    assert store.close_orphaned_meetings() == 3

    lines = store.get_meeting("live-with-lines")
    assert lines["status"] == "ended" and lines["ended_at"] == pytest.approx(1009.5)
    suspended = store.get_meeting("suspended")
    assert suspended["status"] == "ended" and suspended["ended_at"] == pytest.approx(2060.0)
    empty = store.get_meeting("empty")
    assert empty["status"] == "ended" and empty["ended_at"] == pytest.approx(3000.0)
    # Already finished: untouched.
    assert store.get_meeting("finished")["ended_at"] == pytest.approx(4100.0)


def test_it_is_idempotent(store):
    store.create_meeting(conversation_id="c1", meeting_id="m1", started_at=10.0)
    assert store.close_orphaned_meetings() == 1
    assert store.close_orphaned_meetings() == 0
