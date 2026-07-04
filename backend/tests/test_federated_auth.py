"""
Federated sign-in + email login tests.

Covers the additive auth surface:
  • POST /v1/auth/exchange — all three JIT branches (link-by-cloud-id,
    link-by-verified-email, create-new) plus the unverified-email rejection
    and the invalid-token rejection.
  • Local login by email (the "Username or email" field).
  • Federated accounts cannot log in through the local password path
    (account-takeover guard).
  • The pure sliding-window rate limiter.

Notes:
  * The app fixture is session-scoped (shared SQLite), so every test uses unique
    usernames/emails/cloud-ids to stay independent. This module is named to sort
    AFTER test_auth_smoke.py so that suite's first-boot expectations hold.
  * conftest's app fixture purges + reloads ``app.*``; the live ``app.users``
    module (the one the running app uses) is fetched via the ``users`` fixture so
    monkeypatching actually affects the endpoint.
"""
import sys
import uuid

import pytest


def _uniq(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


@pytest.fixture()
def users(app):
    """The live ``app.users`` module used by the running app (post reload)."""
    import importlib
    return sys.modules.get("app.users") or importlib.import_module("app.users")


@pytest.fixture()
def fake_cloud(monkeypatch, users):
    """Patch the Cloud userinfo call so /v1/auth/exchange never hits the network.

    Returns a setter: ``fake_cloud(info_dict_or_None)`` controls what the next
    exchange sees.
    """
    holder = {"info": None}
    monkeypatch.setattr(users, "_fetch_cloud_userinfo", lambda _token: holder["info"])
    return lambda info: holder.__setitem__("info", info)


# ---------------------------------------------------------------------------
# Email-based local login
# ---------------------------------------------------------------------------

class TestEmailLogin:
    def test_login_with_email_identifier(self, client):
        username = _uniq("mail")
        email = f"{username}@example.com"
        r = client.post("/v1/auth/register", json={
            "username": username, "password": "hunter2xx", "email": email,
        })
        assert r.status_code == 200

        # Log in using the EMAIL in the username field.
        r = client.post("/v1/auth/login", json={"username": email, "password": "hunter2xx"})
        assert r.status_code == 200
        assert r.json()["user"]["username"] == username

    def test_email_login_wrong_password(self, client):
        username = _uniq("mail")
        email = f"{username}@example.com"
        client.post("/v1/auth/register", json={
            "username": username, "password": "rightpass1", "email": email,
        })
        r = client.post("/v1/auth/login", json={"username": email, "password": "nope"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# /v1/auth/exchange
# ---------------------------------------------------------------------------

class TestExchange:
    def test_invalid_token_rejected(self, client, fake_cloud):
        fake_cloud(None)  # Cloud userinfo says "unauthenticated"
        r = client.post("/v1/auth/exchange", json={"cloud_token": "garbage_token_00"})
        assert r.status_code == 401

    def test_jit_create_new_user(self, client, fake_cloud, users):
        cloud_id = _uniq("usr_")
        email = f"{_uniq('new')}@example.com"
        fake_cloud({
            "user_id": cloud_id, "email": email, "email_verified": True,
            "display_name": "New Person", "primary_org_id": "org_1",
        })
        r = client.post("/v1/auth/exchange", json={"cloud_token": "cloud_token_val"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["user"]["auth_provider"] == "ollabridge"
        assert body["user"]["email"] == email
        assert len(body["token"]) > 16
        linked = users.get_user_by_cloud_id(cloud_id)
        assert linked is not None and linked["id"] == body["user"]["id"]

    def test_second_exchange_same_cloud_id_returns_same_user(self, client, fake_cloud):
        cloud_id = _uniq("usr_")
        email = f"{_uniq('rep')}@example.com"
        fake_cloud({"user_id": cloud_id, "email": email, "email_verified": True, "display_name": "Rep"})
        first = client.post("/v1/auth/exchange", json={"cloud_token": "cloud_token_a1"}).json()
        second = client.post("/v1/auth/exchange", json={"cloud_token": "cloud_token_b2"}).json()
        assert first["user"]["id"] == second["user"]["id"]  # linked, not duplicated

    def test_link_existing_local_user_by_verified_email(self, client, fake_cloud, users):
        username = _uniq("link")
        email = f"{username}@example.com"
        reg = client.post("/v1/auth/register", json={"username": username, "email": email}).json()
        local_id = reg["user"]["id"]

        cloud_id = _uniq("usr_")
        fake_cloud({"user_id": cloud_id, "email": email, "email_verified": True, "display_name": "Linked"})
        body = client.post("/v1/auth/exchange", json={"cloud_token": "cloud_token_val"}).json()

        # Same local row is reused (linked), not a new one.
        assert body["user"]["id"] == local_id
        assert body["user"]["username"] == username
        linked = users.get_user_by_cloud_id(cloud_id)
        assert linked is not None and linked["id"] == local_id
        assert (linked["auth_provider"] or "local") == "ollabridge"

    def test_unverified_email_does_not_link(self, client, fake_cloud, users):
        username = _uniq("unv")
        email = f"{username}@example.com"
        reg = client.post("/v1/auth/register", json={"username": username, "email": email}).json()
        local_id = reg["user"]["id"]

        cloud_id = _uniq("usr_")
        fake_cloud({"user_id": cloud_id, "email": email, "email_verified": False, "display_name": "Unv"})
        body = client.post("/v1/auth/exchange", json={"cloud_token": "cloud_token_val"}).json()

        # A brand-new federated user is created; the local account is untouched.
        assert body["user"]["id"] != local_id
        assert body["user"]["auth_provider"] == "ollabridge"
        original = users.get_user_by_id(local_id)
        assert not original.get("cloud_user_id")

    def test_federated_user_cannot_local_login(self, client, fake_cloud):
        cloud_id = _uniq("usr_")
        email = f"{_uniq('fed')}@example.com"
        fake_cloud({"user_id": cloud_id, "email": email, "email_verified": True, "display_name": "Fed"})
        body = client.post("/v1/auth/exchange", json={"cloud_token": "cloud_token_val"}).json()
        fed_username = body["user"]["username"]

        # A federated account has no usable local password: the empty-password
        # match must be blocked (otherwise anyone knowing the username gets in).
        r = client.post("/v1/auth/login", json={"username": fed_username, "password": ""})
        assert r.status_code == 401
        r = client.post("/v1/auth/login", json={"username": email, "password": ""})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Rate limiter (pure logic)
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_sliding_window_blocks_after_limit(self, users):
        key = f"unit:{uuid.uuid4().hex}"
        allowed = [users._rate_limit(key, limit=3, window_seconds=60.0) for _ in range(5)]
        assert allowed == [True, True, True, False, False]

    def test_separate_keys_independent(self, users):
        k1, k2 = f"a:{uuid.uuid4().hex}", f"b:{uuid.uuid4().hex}"
        assert users._rate_limit(k1, limit=1, window_seconds=60.0) is True
        assert users._rate_limit(k1, limit=1, window_seconds=60.0) is False
        assert users._rate_limit(k2, limit=1, window_seconds=60.0) is True
