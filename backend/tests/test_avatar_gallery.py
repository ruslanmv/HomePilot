"""Avatar gallery saved per account, and rebuilt from ComfyUI's avatar images."""
import importlib
import os
import sys
import time
import uuid


def _mod():
    return sys.modules.get("app.avatar_gallery") or importlib.import_module("app.avatar_gallery")


def _login(client):
    name = f"av{uuid.uuid4().hex[:8]}"
    r = client.post("/v1/auth/register", json={"username": name, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_requires_sign_in(client):
    assert client.get("/v1/avatar-gallery").status_code == 401


def test_save_and_load_per_account(client):
    a, b = _login(client), _login(client)
    assert client.get("/v1/avatar-gallery", headers=a).json()["items"] is None
    items = [{"id": "gal_1", "url": "/comfy/view/avatar_00001_.png", "mode": "studio_random", "createdAt": 1}]
    assert client.put("/v1/avatar-gallery", json={"items": items}, headers=a).json()["count"] == 1
    assert client.get("/v1/avatar-gallery", headers=a).json()["items"] == items
    # Another account does not see it.
    assert client.get("/v1/avatar-gallery", headers=b).json()["items"] is None


def test_rejects_bad_body(client):
    h = _login(client)
    assert client.put("/v1/avatar-gallery", json={"items": "nope"}, headers=h).status_code == 400


def test_recover_lists_avatar_images_newest_first(client, tmp_path, monkeypatch):
    mod = _mod()
    (tmp_path / "avatar").mkdir()
    files = [
        ("avatar_00001_.png", 100),
        ("avatar_instantid_00002_.png", 300),
        ("avatar/avatar_photomaker_00003_.png", 200),
        ("sd15-uncensored_00004_.png", 400),   # not an avatar
        ("ComfyUI_00005_.png", 500),           # not an avatar
    ]
    for rel, t in files:
        p = tmp_path / rel
        p.write_bytes(b"x")
        os.utime(p, (t, t))
    monkeypatch.setattr(mod, "_comfy_output_dir", lambda: tmp_path)

    h = _login(client)
    data = client.get("/v1/avatar-gallery/recover", headers=h).json()
    assert data["total"] == 3
    urls = [i["url"] for i in data["items"]]
    assert urls == [
        "/comfy/view/avatar_instantid_00002_.png",
        "/comfy/view/avatar_photomaker_00003_.png?subfolder=avatar",
        "/comfy/view/avatar_00001_.png",
    ]
    assert data["items"][0]["mode"] == "studio_reference"
    assert data["items"][0]["createdAt"] == 300_000
    assert len({i["id"] for i in data["items"]}) == 3

    limited = client.get("/v1/avatar-gallery/recover?limit=1", headers=h).json()
    assert len(limited["items"]) == 1 and limited["total"] == 3
