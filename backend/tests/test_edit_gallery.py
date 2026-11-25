"""Edit Studio gallery rebuilt from stored edit sessions."""
import importlib
import json
import sqlite3
import sys
import uuid


def _mod():
    return sys.modules.get("app.edit_gallery") or importlib.import_module("app.edit_gallery")


def _login(client):
    r = client.post("/v1/auth/register", json={"username": f"ed{uuid.uuid4().hex[:8]}", "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_recover_lists_sessions_newest_first_and_skips_missing(client, tmp_path, monkeypatch):
    mod = _mod()
    db = tmp_path / "edit_sessions.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE edit_sessions(conversation_id TEXT PRIMARY KEY, active_image_url TEXT, "
                "history_json TEXT, updated_at REAL, original_image_url TEXT)")
    rows = [
        ("old", "http://localhost:8000/files/a.png", json.dumps(["x", "y"]), 100.0, "http://localhost:8000/files/o.png"),
        ("new", "http://localhost:8188/view?filename=homepilot_edit_00001_.png&type=output", "[]", 200.0, None),
        ("gone", "http://localhost:8000/files/missing.png", "[]", 300.0, None),
    ]
    con.executemany("INSERT INTO edit_sessions VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()
    monkeypatch.setattr(mod, "edit_sessions_db", lambda: db)
    monkeypatch.setattr(mod, "_exists", lambda url: "missing" not in url)

    data = client.get("/v1/edit-gallery/recover", headers=_login(client)).json()
    assert data["total"] == 3 and data["skipped_missing"] == 1
    assert [i["conversationId"] for i in data["items"]] == ["new", "old"]
    old = data["items"][1]
    assert old["url"] == "/files/a.png" and old["originalUrl"] == "/files/o.png"
    assert old["createdAt"] == 100_000 and old["settings"]["versions"] == 2


def test_recover_requires_sign_in(client):
    assert client.get("/v1/edit-gallery/recover").status_code == 401
