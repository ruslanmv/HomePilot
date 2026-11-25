"""Logging out ends the cookie session too, so the next page load does not sign back in."""
import importlib
import sys
import uuid


def test_logout_with_only_the_cookie_ends_that_session(app, client):
    users = sys.modules.get("app.users") or importlib.import_module("app.users")
    name = f"lo{uuid.uuid4().hex[:8]}"
    r = client.post("/v1/auth/register", json={"username": name, "password": "pw123456"})
    token = r.json()["token"]
    assert users._validate_token(token)

    # The browser sends only the HttpOnly cookie (no Authorization header).
    client.cookies.set("homepilot_session", token)
    assert client.post("/v1/auth/logout").status_code == 200
    assert users._validate_token(token) is None

    client.cookies.set("homepilot_session", token)
    me = client.get("/v1/auth/me").json()
    assert (me.get("user") or {}).get("username") != name
    client.cookies.clear()


def test_logout_ends_header_and_cookie_sessions(app, client):
    users = sys.modules.get("app.users") or importlib.import_module("app.users")
    name = f"lb{uuid.uuid4().hex[:8]}"
    t1 = client.post("/v1/auth/register", json={"username": name, "password": "pw123456"}).json()["token"]
    t2 = client.post("/v1/auth/login", json={"username": name, "password": "pw123456"}).json()["token"]
    client.cookies.set("homepilot_session", t2)
    client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {t1}"})
    assert users._validate_token(t1) is None
    assert users._validate_token(t2) is None
    client.cookies.clear()
