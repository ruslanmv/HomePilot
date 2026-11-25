"""
Local-account password reset: one-time code delivered on the host.

The code is never returned over HTTP, so each test reads it the way an owner
would: from the file the server writes into ``<data dir>/password-reset/``.
"""
import importlib
import os
import sys
import uuid

import pytest


def _uniq(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


@pytest.fixture(autouse=True)
def web_reset_on(monkeypatch):
    """The web flow is opt-in; most tests here exercise it."""
    monkeypatch.setenv("HOMEPILOT_PASSWORD_RESET", "1")


@pytest.fixture()
def pr(app):
    return sys.modules.get("app.password_reset") or importlib.import_module("app.password_reset")


def _register(client, username, password="oldpassw0rd", email=""):
    r = client.post("/v1/auth/register", json={
        "username": username, "password": password, "email": email,
    })
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _read_code(pr, username):
    with open(os.path.join(pr.reset_dir(), f"{username}.txt"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("Code:"):
                return line.split(":", 1)[1].strip()
    raise AssertionError("no code in reset file")


def test_full_reset_flow(client, pr):
    username = _uniq("reset")
    old_token = _register(client, username)

    r = client.post("/v1/auth/password-reset/request", json={"identifier": username})
    assert r.status_code == 200
    assert "code" not in r.json()
    code = _read_code(pr, username)

    r = client.post("/v1/auth/password-reset/confirm", json={
        "identifier": username, "code": code.lower(), "new_password": "brandnewpass",
    })
    assert r.status_code == 200, r.text
    assert r.json()["token"]

    # Old password and old sessions are gone; new password works.
    assert client.post("/v1/auth/login", json={"username": username, "password": "oldpassw0rd"}).status_code == 401
    assert client.post("/v1/auth/login", json={"username": username, "password": "brandnewpass"}).status_code == 200
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"}).json()
    assert (me.get("user") or {}).get("username") != username

    # The code is single use and its file is removed.
    assert not os.path.exists(os.path.join(pr.reset_dir(), f"{username}.txt"))
    r = client.post("/v1/auth/password-reset/confirm", json={
        "identifier": username, "code": code, "new_password": "anotherpass1",
    })
    assert r.status_code == 400


def test_request_reply_does_not_reveal_accounts(client):
    username = _uniq("exists")
    _register(client, username)
    a = client.post("/v1/auth/password-reset/request", json={"identifier": username}).json()
    b = client.post("/v1/auth/password-reset/request", json={"identifier": _uniq("nobody")}).json()
    assert a == b


def test_reset_by_email(client, pr):
    username = _uniq("mailreset")
    _register(client, username, email=f"{username}@example.com")
    client.post("/v1/auth/password-reset/request", json={"identifier": f"{username}@example.com"})
    code = _read_code(pr, username)
    r = client.post("/v1/auth/password-reset/confirm", json={
        "identifier": f"{username}@example.com", "code": code, "new_password": "viaemail123",
    })
    assert r.status_code == 200, r.text


def test_wrong_codes_burn_the_code(client, pr):
    username = _uniq("brute")
    _register(client, username)
    client.post("/v1/auth/password-reset/request", json={"identifier": username})
    code = _read_code(pr, username)
    for _ in range(pr.MAX_ATTEMPTS):
        r = client.post("/v1/auth/password-reset/confirm", json={
            "identifier": username, "code": "AAAAA-AAAAA", "new_password": "whatever123",
        })
        assert r.status_code == 400
    r = client.post("/v1/auth/password-reset/confirm", json={
        "identifier": username, "code": code, "new_password": "whatever123",
    })
    assert r.status_code == 400


def test_expired_code_is_rejected(client, pr, monkeypatch):
    username = _uniq("expire")
    _register(client, username)
    client.post("/v1/auth/password-reset/request", json={"identifier": username})
    code = _read_code(pr, username)
    real_time = pr.time.time
    monkeypatch.setattr(pr.time, "time", lambda: real_time() + pr.CODE_TTL_SECONDS + 5)
    r = client.post("/v1/auth/password-reset/confirm", json={
        "identifier": username, "code": code, "new_password": "toolate1234",
    })
    assert r.status_code == 400


def test_short_password_rejected(client, pr):
    username = _uniq("short")
    _register(client, username)
    client.post("/v1/auth/password-reset/request", json={"identifier": username})
    code = _read_code(pr, username)
    r = client.post("/v1/auth/password-reset/confirm", json={
        "identifier": username, "code": code, "new_password": "short",
    })
    assert r.status_code == 400
    # The code survives a validation error so the user can retry.
    r = client.post("/v1/auth/password-reset/confirm", json={
        "identifier": username, "code": code, "new_password": "longenough1",
    })
    assert r.status_code == 200


@pytest.mark.parametrize("value", [None, "0"])
def test_web_reset_is_off_by_default(client, pr, monkeypatch, value):
    """Without an explicit opt-in, the sign-in page cannot reset a local password."""
    if value is None:
        monkeypatch.delenv("HOMEPILOT_PASSWORD_RESET", raising=False)
    else:
        monkeypatch.setenv("HOMEPILOT_PASSWORD_RESET", value)
    username = _uniq("termonly")
    _register(client, username)
    assert client.get("/v1/auth/password-reset/status").json()["enabled"] is False
    r = client.post("/v1/auth/password-reset/request", json={"identifier": username})
    assert r.status_code == 403
    assert not os.path.exists(os.path.join(pr.reset_dir(), f"{username}.txt"))
    r = client.post("/v1/auth/password-reset/confirm", json={
        "identifier": username, "code": "AAAAA-AAAAA", "new_password": "whatever123",
    })
    assert r.status_code == 403


def test_cli_sets_password(client, pr, monkeypatch, capsys):
    username = _uniq("cli")
    _register(client, username)
    answers = iter(["fromthecli1", "fromthecli1"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": next(answers))
    assert pr.main([username, "--set-password"]) == 0
    assert client.post("/v1/auth/login", json={"username": username, "password": "fromthecli1"}).status_code == 200


def test_cli_prints_code(client, pr, capsys):
    username = _uniq("clicode")
    _register(client, username)
    assert pr.main([username]) == 0
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("Reset code for"))
    code = line.rsplit(" ", 1)[1]
    r = client.post("/v1/auth/password-reset/confirm", json={
        "identifier": username, "code": code, "new_password": "codefromcli1",
    })
    assert r.status_code == 200, r.text
