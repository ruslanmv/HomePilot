"""
"Continue with Hugging Face": the sign-in window flow. A one-use state ties the window to the
signed-in user; Accept links the account; the token never reaches the browser; a cancelled,
replayed or expired sign-in links nothing.
"""
from __future__ import annotations

import sys
import time
import uuid
from urllib.parse import parse_qs, urlparse


def _user(client):
    r = client.post("/v1/auth/register", json={"username": f"o{uuid.uuid4().hex[:10]}"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _oauth():
    return sys.modules["app.connectors.oauth"]


def _hf_row(client, h):
    return next(c for c in client.get("/v1/connectors", headers=h).json()["connectors"] if c["id"] == "huggingface")


def _enable(monkeypatch):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "client-123")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "secret-456")
    monkeypatch.setenv("OAUTH_SCOPES", "openid profile inference-api")
    monkeypatch.setenv("SPACE_HOST", "someone-homepilot.hf.space")


def _fake_exchange(monkeypatch, expires_in=3600):
    seen = {}

    async def exchange(code, pending):
        seen.update(code=code, verifier=pending["verifier"], redirect_uri=pending["redirect_uri"])
        return {"token": "hf_oauth_token_xyz", "account": "ada",
                "meta": {"via": "oauth", "avatar": "https://a/ada.png",
                         "expires_at": time.time() + expires_in}}
    monkeypatch.setattr(_oauth(), "exchange", exchange)
    return seen


def _start(client, h):
    r = client.post("/v1/connectors/huggingface/oauth/start", headers=h)
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["url"]).query)
    return r.json()["url"], {k: v[0] for k, v in q.items()}


def test_without_an_oauth_app_only_the_token_form_is_offered(client, monkeypatch):
    for k in ("OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET", "HOMEPILOT_HF_OAUTH_CLIENT_ID", "HOMEPILOT_HF_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    h = _user(client)
    assert _hf_row(client, h)["oauth"] is False
    assert client.post("/v1/connectors/huggingface/oauth/start", headers=h).status_code == 404


def test_start_asks_hugging_face_with_pkce_and_the_space_callback(client, monkeypatch):
    _enable(monkeypatch)
    h = _user(client)
    assert _hf_row(client, h)["oauth"] is True
    url, q = _start(client, h)
    assert url.startswith("https://huggingface.co/oauth/authorize?")
    assert q["client_id"] == "client-123" and q["response_type"] == "code"
    assert q["redirect_uri"] == "https://someone-homepilot.hf.space/v1/connectors/huggingface/oauth/callback"
    assert "inference-api" in q["scope"].split()
    assert q["code_challenge_method"] == "S256" and len(q["state"]) > 20
    assert "secret-456" not in url


def test_accept_links_the_account_and_closes_the_window(client, monkeypatch):
    _enable(monkeypatch)
    seen = _fake_exchange(monkeypatch)
    h = _user(client)
    _, q = _start(client, h)
    r = client.get(f"/v1/connectors/huggingface/oauth/callback?code=c0de&state={q['state']}")
    assert r.status_code == 200 and "homepilot:connector" in r.text and "window.close" in r.text
    assert "hf_oauth_token_xyz" not in r.text
    assert seen["code"] == "c0de" and seen["redirect_uri"] == q["redirect_uri"]
    row = _hf_row(client, h)
    assert row["connected"] is True and row["account"] == "ada" and row["via"] == "oauth"
    assert row["avatar"] == "https://a/ada.png"
    assert "hf_oauth_token_xyz" not in client.get("/v1/connectors", headers=h).text
    hf = sys.modules["app.connectors.huggingface"]
    users = sys.modules["app.users"]
    uid = users._validate_token(h["Authorization"].split()[1])["id"]
    assert hf.token(uid) == "hf_oauth_token_xyz"


def test_a_state_works_once(client, monkeypatch):
    _enable(monkeypatch)
    _fake_exchange(monkeypatch)
    h = _user(client)
    _, q = _start(client, h)
    client.get(f"/v1/connectors/huggingface/oauth/callback?code=c&state={q['state']}")
    again = client.get(f"/v1/connectors/huggingface/oauth/callback?code=c&state={q['state']}")
    assert again.status_code == 400 and "expired" in again.text


def test_an_unknown_state_links_nobody(client, monkeypatch):
    _enable(monkeypatch)
    _fake_exchange(monkeypatch)
    r = client.get("/v1/connectors/huggingface/oauth/callback?code=c&state=made-up")
    assert r.status_code == 400


def test_cancel_on_hugging_face_says_so(client, monkeypatch):
    _enable(monkeypatch)
    h = _user(client)
    _, q = _start(client, h)
    r = client.get(f"/v1/connectors/huggingface/oauth/callback?error=access_denied&state={q['state']}")
    assert "cancelled" in r.text
    assert _hf_row(client, h)["connected"] is False


def test_an_expired_sign_in_shows_as_reconnect_and_is_not_used(client, monkeypatch):
    _enable(monkeypatch)
    _fake_exchange(monkeypatch, expires_in=-5)
    h = _user(client)
    _, q = _start(client, h)
    client.get(f"/v1/connectors/huggingface/oauth/callback?code=c&state={q['state']}")
    row = _hf_row(client, h)
    assert row["connected"] is False and row["expired"] is True
