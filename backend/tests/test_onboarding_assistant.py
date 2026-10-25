"""
The first conversation: every account gets one assistant named HomePilot, created before it
speaks, and its first chat is the onboarding. A second call, tab or login finds the same one.
On the web edition each visitor is a guest account of their own.
"""
from __future__ import annotations

import sys
import uuid


def _user(client, name=""):
    username = f"u{uuid.uuid4().hex[:10]}"
    r = client.post("/v1/auth/register", json={"username": username, "display_name": name or username})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _texts(state):
    return [m["content"] for m in state["messages"]]


def test_the_assistant_exists_before_it_speaks(client):
    h = _user(client, "ruslan magana")
    state = client.post("/v1/onboarding/assistant", headers=h).json()
    assert state["created"] is True and state["step"] == "created"
    assert state["assistant"]["name"] == "HomePilot"
    assert _texts(state) == [
        "Hi Ruslan! I'm HomePilot.",
        "What would you like to call me? You can always change this later.",
    ]


def test_once_per_account(client):
    h = _user(client)
    first = client.post("/v1/onboarding/assistant", headers=h).json()
    again = client.post("/v1/onboarding/assistant", headers=h).json()
    assert again["created"] is False
    assert again["assistant"]["id"] == first["assistant"]["id"]
    assert again["conversation_id"] == first["conversation_id"]
    assert _texts(again) == _texts(first)  # a refresh shows the same thread, not a replay
    assert client.get("/v1/onboarding/assistant", headers=h).json()["assistant"]["id"] == first["assistant"]["id"]


def test_keeping_the_name_introduces_the_assistant(client):
    h = _user(client, "ada")
    client.post("/v1/onboarding/assistant", headers=h)
    state = client.post("/v1/onboarding/name", json={}, headers=h).json()
    assert state["accepted"] is True and state["step"] == "introduced"
    texts = _texts(state)
    assert texts[2] == "HomePilot it is! Nice to meet you, Ada."
    assert texts[3].startswith("A little about me:")
    # A second tap writes nothing more.
    assert _texts(client.post("/v1/onboarding/name", json={}, headers=h).json()) == texts


def test_a_typed_name_renames_the_assistant(client):
    h = _user(client)
    created = client.post("/v1/onboarding/assistant", headers=h).json()
    state = client.post("/v1/onboarding/name", json={"name": "  Jarvis "}, headers=h).json()
    assert state["assistant"]["name"] == "Jarvis"
    assert "Jarvis" in state["assistant"]["instructions"]
    assert {"role": "user", "content": "Jarvis", "onboarding": "named"} in state["messages"]
    assert _texts(state)[3].startswith("Jarvis it is! Nice to meet you")
    project = client.get(f"/projects/{created['assistant']['id']}", headers=h).json()["project"]
    assert project["name"] == "Jarvis"


def test_a_question_is_a_message_not_a_name(client):
    h = _user(client)
    client.post("/v1/onboarding/assistant", headers=h)
    state = client.post("/v1/onboarding/name", json={"name": "what's the weather in Rome?"}, headers=h).json()
    assert state["accepted"] is False
    assert state["assistant"]["name"] == "HomePilot" and state["step"] == "created"


def test_done_finishes_onboarding(client):
    h = _user(client)
    client.post("/v1/onboarding/assistant", headers=h)
    state = client.post("/v1/onboarding/done", headers=h).json()
    assert state["step"] == "done" and state["complete"] is True
    assert client.get("/v1/auth/me", headers=h).json()["user"]["onboarding_complete"] is True


def test_an_assistant_lost_from_disk_is_made_again(client):
    h = _user(client)
    first = client.post("/v1/onboarding/assistant", headers=h).json()
    projects = sys.modules["app.projects"]
    db = projects._load_projects_db()
    db.pop(first["assistant"]["id"])
    projects._save_projects_db(db)
    again = client.post("/v1/onboarding/assistant", headers=h).json()
    assert again["created"] is True and again["assistant"]["id"] != first["assistant"]["id"]


def test_each_account_sees_only_its_own_assistant_in_projects(client):
    a, b = _user(client), _user(client)
    mine = client.post("/v1/onboarding/assistant", headers=a).json()["assistant"]["id"]
    theirs = client.post("/v1/onboarding/assistant", headers=b).json()["assistant"]["id"]
    listed = {p["id"] for p in client.get("/projects", headers=a).json()["projects"]}
    assert mine in listed and theirs not in listed


def test_signed_out_is_refused(client, monkeypatch):
    monkeypatch.setattr(sys.modules["app.config"], "HOMEPILOT_EDITION", "local")
    _user(client)  # more than one account: no anonymous fallback
    client.cookies.clear()  # registering left a session cookie in the test client
    assert client.post("/v1/onboarding/assistant").status_code == 401


def test_web_edition_visitors_are_separate_guests(client, monkeypatch):
    monkeypatch.setattr(sys.modules["app.config"], "HOMEPILOT_EDITION", "web")
    assert client.get("/v1/auth/me").json()["needs_guest"] is True
    one = client.post("/v1/auth/guest").json()
    two = client.post("/v1/auth/guest").json()
    assert one["user"]["id"] != two["user"]["id"] and one["user"]["onboarding_complete"] is False
    h1 = {"Authorization": f"Bearer {one['token']}"}
    h2 = {"Authorization": f"Bearer {two['token']}"}
    s1 = client.post("/v1/onboarding/assistant", headers=h1).json()
    s2 = client.post("/v1/onboarding/assistant", headers=h2).json()
    assert s1["assistant"]["id"] != s2["assistant"]["id"]
    assert _texts(s1)[0] == "Hi there! I'm HomePilot."  # a guest id is never used as a name
    # One visitor cannot read the other's thread.
    r = client.get(f"/conversations/{s1['conversation_id']}/messages", headers=h2)
    assert r.status_code != 200 or not r.json().get("messages")
    # A guest is never the install's default user.
    users = sys.modules["app.users"]
    assert users.get_or_create_default_user().get("auth_provider", "local") != "guest"


def test_guests_are_off_on_a_local_install(client, monkeypatch):
    monkeypatch.setattr(sys.modules["app.config"], "HOMEPILOT_EDITION", "local")
    assert client.post("/v1/auth/guest").status_code == 404


def test_starters_offer_only_what_this_install_can_do(client, monkeypatch):
    config = sys.modules["app.config"]
    h = _user(client)
    monkeypatch.setenv("SPACE_ID", "ruslanmv/HomePilot")
    monkeypatch.setattr(config, "COMFY_BASE_URL", "")
    ids = [s["id"] for s in client.post("/v1/onboarding/assistant", headers=h).json()["starters"]]
    assert "image" not in ids and "meeting" not in ids and len(ids) == 4  # a CPU Space: chat only
    monkeypatch.delenv("SPACE_ID")
    monkeypatch.setattr(config, "COMFY_BASE_URL", "http://127.0.0.1:8188")
    local = client.get("/v1/onboarding/assistant", headers=h).json()["starters"]
    assert [s["id"] for s in local][:3] == ["image", "meeting", "voice"] and len(local) == 4
    assert all(s["kind"] in ("prompt", "mode") for s in local)


def test_the_introduction_claims_only_what_is_connected(client, monkeypatch):
    config = sys.modules["app.config"]
    monkeypatch.setenv("SPACE_ID", "ruslanmv/HomePilot")
    monkeypatch.setenv("EXPERT_TOOLS_ENABLED", "0")
    monkeypatch.setattr(config, "COMFY_BASE_URL", "")
    h = _user(client)
    client.post("/v1/onboarding/assistant", headers=h)
    about = _texts(client.post("/v1/onboarding/name", json={}, headers=h).json())[3]
    assert "on this Space" in about and "look things up" not in about and "images" not in about
