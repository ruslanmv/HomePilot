"""Imagine history is rebuilt from the account's own conversations, newest first."""
import importlib
import json
import sqlite3
import sys
import uuid


def _mod(name):
    return sys.modules.get(name) or importlib.import_module(name)


def _setup(app):
    users = _mod("app.users")
    tag = uuid.uuid4().hex[:8]
    me = users.create_user(username=f"im{tag}", password="pw123456")
    other = users.create_user(username=f"io{tag}", password="pw123456")
    con = sqlite3.connect(users._get_db_path())
    con.execute("CREATE TABLE IF NOT EXISTS conversation_owners(conversation_id TEXT PRIMARY KEY, user_id TEXT)")

    def conv(owner, msgs):
        cid = f"c_{uuid.uuid4().hex[:10]}"
        con.execute("INSERT INTO conversation_owners(conversation_id, user_id) VALUES (?, ?)", (cid, owner))
        for role, content, media, ts in msgs:
            con.execute(
                "INSERT INTO messages(conversation_id, role, content, media, created_at) VALUES (?, ?, ?, ?, ?)",
                (cid, role, content, json.dumps(media) if media else None, ts),
            )

    comfy = "http://localhost:8188/view?filename=sd_00001_.png&subfolder=&type=output"
    conv(me["id"], [
        ("user", "imagine a red fox", None, "2026-01-01 10:00:00"),
        ("assistant", "", {"images": [comfy], "final_prompt": "a red fox, detailed", "model": "sdxl"}, "2026-01-01 10:00:05"),
    ])
    conv(me["id"], [
        ("user", "imagine a blue bird", None, "2026-02-01 10:00:00"),
        ("assistant", "", {"images": ["http://localhost:8000/files/f_abc", comfy]}, "2026-02-01 10:00:05"),
    ])
    conv(me["id"], [  # a normal chat that happened to return an image: not Imagine
        ("user", "what is in this picture?", None, "2026-03-01 10:00:00"),
        ("assistant", "", {"images": ["/files/f_chat"]}, "2026-03-01 10:00:05"),
    ])
    conv(other["id"], [  # another account's image never shows
        ("user", "imagine a cat", None, "2026-04-01 10:00:00"),
        ("assistant", "", {"images": ["/files/f_cat"]}, "2026-04-01 10:00:05"),
    ])
    con.commit()
    con.close()
    return users, me


def test_history_is_own_imagine_images_newest_first(app, client):
    users, me = _setup(app)
    h = {"Authorization": f"Bearer {users._create_token(me['id'])}"}
    data = client.get("/v1/imagine/history", headers=h).json()
    urls = [i["url"] for i in data["items"]]
    # Newest first; the repeated ComfyUI image appears once; ComfyUI links go through the backend.
    assert urls == ["/files/f_abc", "/comfy/view/sd_00001_.png"]
    assert data["total"] == 2
    fox = data["items"][1]
    assert fox["prompt"] == "a red fox, detailed" and fox["model"] == "sdxl" and fox["status"] == "done"
    assert data["items"][0]["prompt"] == "a blue bird"


def test_history_paging_and_sign_in(app, client):
    users, me = _setup(app)
    h = {"Authorization": f"Bearer {users._create_token(me['id'])}"}
    page = client.get("/v1/imagine/history?limit=1&offset=1", headers=h).json()
    assert [i["url"] for i in page["items"]] == ["/comfy/view/sd_00001_.png"]
    assert client.get("/v1/imagine/history").status_code == 401
