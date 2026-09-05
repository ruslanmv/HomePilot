"""Naming a meeting a person can reach (batch MS33, wave W13).

MS17 gave a meeting a title from a calendar event or a shared window title, and `UPDATABLE`
has always allowed the columns somebody might want to correct. Nothing could reach them:
naming a meeting was a capability with no door. The `•••` menu needs one, so here it is.

Renaming is the safe end of MS33's rule — *safe actions happen immediately, destructive ones
take a second intention*. It changes a label and the previous title is one more rename away,
so unlike the delete beneath it in the same menu it takes no confirmation.

What is actually tested is the boundary, because the route is four lines and the store's
guarantees are the interesting part: an unknown column must not be written, an empty value
must not erase a title a calendar found, and "nothing was written" must not be reported as
success.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("MEETINGSENSE_ENABLED", "MEETINGSENSE_RETENTION"):
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.config as config
        import app.meetingsense.routes as routes
        import app.meetingsense.session as session
        import app.meetingsense.store as store

        self.config = config
        self.routes = routes
        self.session = session
        self.store = store


@pytest.fixture()
def modules(tmp_path, monkeypatch):
    mods = Modules()
    db = tmp_path / "meetings.sqlite3"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(mods.store, "_connect", _connect)
    mods.store.migrate()
    mods.session._SESSIONS.clear()
    return mods


@pytest.fixture()
def client(modules, monkeypatch):
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
    app = FastAPI()
    app.include_router(modules.routes.router)
    return TestClient(app)


def meeting(mods, mid="m1", *, title="Microsoft Teams"):
    mods.store.create_meeting(conversation_id="c1", meeting_id=mid, title=title,
                              source="teams", started_at=1_700_000_000.0)
    return mid


def test_renames_a_meeting(client, modules):
    meeting(modules)
    res = client.patch("/v1/meetingsense/m1", json={"title": "1:1 with Ana"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["written"] == ["title"]
    assert body["meeting"]["title"] == "1:1 with Ana"
    # And it is the store that changed, not just the response.
    assert modules.store.get_meeting("m1")["title"] == "1:1 with Ana"


def test_an_empty_title_never_erases_the_one_that_is_there(client, modules):
    """`store.update_meeting` refuses empty values, and the route refuses to call it a win.

    MS17's rule is that an empty answer is not an answer. A blank title arriving from a
    cleared input must leave the calendar's title exactly where it was, and must not come
    back 200 — a success for a write that did not happen is how a UI ends up showing a name
    the database does not have.
    """
    meeting(modules)
    res = client.patch("/v1/meetingsense/m1", json={"title": "   "})
    assert res.status_code == 400
    assert modules.store.get_meeting("m1")["title"] == "Microsoft Teams"


def test_refuses_a_body_with_nothing_writable(client, modules):
    meeting(modules)
    res = client.patch("/v1/meetingsense/m1", json={})
    assert res.status_code == 400
    res = client.patch("/v1/meetingsense/m1", json={"nonsense": "x"})
    assert res.status_code == 400


def test_cannot_write_a_column_that_is_not_updatable(client, modules):
    """The guard is the store's `UPDATABLE`, so it holds for every caller and not just this one.

    `started_at` and `conversation_id` are facts about what happened. A rename endpoint that
    could move a meeting to another conversation would be a rename endpoint in name only.
    """
    meeting(modules)
    before = dict(modules.store.get_meeting("m1"))
    res = client.patch("/v1/meetingsense/m1", json={"conversation_id": "c-other", "started_at": 1.0})
    assert res.status_code == 400
    after = dict(modules.store.get_meeting("m1"))
    assert after["conversation_id"] == before["conversation_id"]
    assert after["started_at"] == before["started_at"]


def test_a_writable_field_alongside_an_unwritable_one_writes_only_the_first(client, modules):
    meeting(modules)
    res = client.patch("/v1/meetingsense/m1", json={"title": "Renamed", "conversation_id": "c-other"})
    assert res.status_code == 200
    assert res.json()["written"] == ["title"]
    assert modules.store.get_meeting("m1")["conversation_id"] == "c1"


def test_unknown_meeting_is_a_404(client, modules):
    assert client.patch("/v1/meetingsense/nope", json={"title": "x"}).status_code == 404


def test_disabled_server_does_not_expose_it(modules, monkeypatch):
    monkeypatch.delenv("MEETINGSENSE_ENABLED", raising=False)
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "false")
    meeting(modules)
    app = FastAPI()
    app.include_router(modules.routes.router)
    res = TestClient(app).patch("/v1/meetingsense/m1", json={"title": "x"})
    assert res.status_code in (403, 404, 503)
