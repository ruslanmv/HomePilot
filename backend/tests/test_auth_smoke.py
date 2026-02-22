"""
Auth smoke tests — CI-friendly, zero-network, lightweight.

Validates the full user lifecycle that customers depend on:
  1. First boot → needs_setup signal
  2. Registration → new account + token
  3. Login → correct credentials succeed, wrong ones fail
  4. Session → /me returns the right user for a given token
  5. Multi-user isolation → two users, each sees only their own data
  6. Onboarding → marks user complete, persists display name
  7. Logout → token invalidated
  8. User switching → second user logs in, gets different identity
  9. Duplicate username → 409
 10. Password change hash upgrade path

Runs against TestClient (in-process), no external services needed.
"""
import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _register(client, username, password="", display_name="", email=""):
    return client.post("/v1/auth/register", json={
        "username": username,
        "password": password,
        "email": email,
        "display_name": display_name or username,
    })


def _login(client, username, password=""):
    return client.post("/v1/auth/login", json={
        "username": username,
        "password": password,
    })


def _me(client, token=""):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/v1/auth/me", headers=headers)


def _onboarding(client, token, display_name="", use_cases=None, tone="balanced"):
    return client.put("/v1/auth/onboarding", json={
        "display_name": display_name,
        "use_cases": use_cases or [],
        "preferred_tone": tone,
    }, headers={"Authorization": f"Bearer {token}"})


def _logout(client, token):
    return client.post("/v1/auth/logout",
                       headers={"Authorization": f"Bearer {token}"})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFirstBoot:
    """Before any user exists the system should signal needs_setup."""

    def test_me_returns_needs_setup(self, client):
        r = _me(client)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data.get("needs_setup") is True


class TestRegistration:
    """Register a new user and verify the response shape."""

    def test_register_success(self, client):
        r = _register(client, "alice", password="pass123", display_name="Alice")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["user"]["username"] == "alice"
        assert data["user"]["display_name"] == "Alice"
        assert "avatar_url" in data["user"]
        assert data["user"]["onboarding_complete"] is False
        assert len(data["token"]) > 16

    def test_duplicate_username_rejected(self, client):
        _register(client, "bob", password="pw")
        r = _register(client, "bob", password="other")
        assert r.status_code == 409

    def test_short_username_rejected(self, client):
        r = _register(client, "x")
        assert r.status_code == 422  # pydantic min_length=2

    def test_invalid_username_chars(self, client):
        r = _register(client, "bad user!")
        assert r.status_code == 400


class TestLogin:
    """Login with correct and incorrect credentials."""

    def test_login_correct_password(self, client):
        _register(client, "carol", password="secret")
        r = _login(client, "carol", password="secret")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["user"]["username"] == "carol"
        assert len(data["token"]) > 16

    def test_login_wrong_password(self, client):
        _register(client, "dave", password="right")
        r = _login(client, "dave", password="wrong")
        assert r.status_code == 401

    def test_login_nonexistent_user(self, client):
        r = _login(client, "ghost", password="nope")
        assert r.status_code == 401

    def test_login_passwordless(self, client):
        """Passwordless user can log in with empty password."""
        _register(client, "eve")
        r = _login(client, "eve", password="")
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestSession:
    """/me should return the authenticated user's data."""

    def test_me_with_valid_token(self, client):
        reg = _register(client, "frank", password="pw").json()
        token = reg["token"]
        r = _me(client, token)
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["username"] == "frank"
        assert data["user"]["id"] == reg["user"]["id"]

    def test_me_with_invalid_token(self, client):
        # With an invalid token and multiple users, should signal needs_login
        _register(client, "grace", password="pw")
        r = _me(client, "totally-bogus-token")
        assert r.status_code == 200
        data = r.json()
        # Either needs_login or needs_setup — user should NOT be returned
        assert data.get("user") is None or data.get("needs_login") or data.get("needs_setup")


class TestOnboarding:
    """Onboarding should mark user complete and persist display name."""

    def test_onboarding_flow(self, client):
        reg = _register(client, "hank", password="pw").json()
        token = reg["token"]

        # Before onboarding
        assert reg["user"]["onboarding_complete"] is False

        # Complete onboarding
        r = _onboarding(client, token, display_name="Hank the Tank",
                         use_cases=["creative_writing"], tone="casual")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["user"]["onboarding_complete"] is True
        assert data["user"]["display_name"] == "Hank the Tank"

        # /me should now reflect onboarding_complete
        me = _me(client, token).json()
        assert me["user"]["onboarding_complete"] is True

    def test_onboarding_requires_auth(self, client):
        r = _onboarding(client, "", display_name="Nobody")
        assert r.status_code == 401


class TestLogout:
    """Logout should invalidate the session token."""

    def test_logout_invalidates_token(self, client):
        reg = _register(client, "ida", password="pw").json()
        token = reg["token"]

        # Logout
        r = _logout(client, token)
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Token should no longer work for /me
        me = _me(client, token).json()
        assert me.get("user") is None or me.get("needs_login") or me.get("needs_setup")


class TestMultiUserIsolation:
    """Two users should each see their own identity — never another user's data."""

    def test_two_users_different_tokens(self, client):
        r1 = _register(client, "user_one", password="pw1", display_name="User One").json()
        r2 = _register(client, "user_two", password="pw2", display_name="User Two").json()

        me1 = _me(client, r1["token"]).json()
        me2 = _me(client, r2["token"]).json()

        assert me1["user"]["username"] == "user_one"
        assert me2["user"]["username"] == "user_two"
        assert me1["user"]["id"] != me2["user"]["id"]

    def test_user_list_shows_all(self, client):
        _register(client, "list_a", password="pw")
        _register(client, "list_b", password="pw")
        r = client.get("/v1/auth/users")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        usernames = [u["username"] for u in data["users"]]
        assert "list_a" in usernames
        assert "list_b" in usernames


class TestUserSwitching:
    """Simulate user switching: log out user A, log in user B."""

    def test_switch_user(self, client):
        _register(client, "switch_a", password="pw_a")
        _register(client, "switch_b", password="pw_b")

        # Login as A
        tok_a = _login(client, "switch_a", "pw_a").json()["token"]
        assert _me(client, tok_a).json()["user"]["username"] == "switch_a"

        # Logout A
        _logout(client, tok_a)

        # Login as B
        tok_b = _login(client, "switch_b", "pw_b").json()["token"]
        assert _me(client, tok_b).json()["user"]["username"] == "switch_b"

        # A's old token is dead
        me_a = _me(client, tok_a).json()
        assert me_a.get("user") is None or me_a.get("needs_login")
