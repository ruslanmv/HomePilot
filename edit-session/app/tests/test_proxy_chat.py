"""
Tests for the chat proxy endpoint.
"""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app
from app.store import SQLiteStore
from app import homepilot_client
from app import security as security_module


@pytest.fixture
def store(tmp_path):
    """Create temporary store for direct access in tests."""
    db = tmp_path / "db.sqlite"
    return SQLiteStore(str(db))


@pytest.fixture
def client(store, monkeypatch):
    """Create test client using the shared store."""
    # Patch on the module where get_store is used, not where it's defined
    monkeypatch.setattr(main_module, "get_store", lambda: store)
    # Reset rate limiter for each test
    security_module.bucket.tokens.clear()
    security_module.bucket.updated.clear()
    return TestClient(app)


class TestProxyChatEndpoint:
    """Test suite for /chat proxy endpoint."""

    def test_proxy_chat_rewrites_edit_when_no_url(
        self, client, store, monkeypatch
    ):
        """Chat in edit mode rewrites message to include active image URL."""
        # Set active image
        store.set_active("c1", "http://homepilot/files/img.png")

        # Mock HomePilot client
        async def fake_chat(self, payload):
            # Verify rewritten message
            assert payload["mode"] == "edit"
            assert payload["conversation_id"] == "c1"
            assert payload["message"].startswith("edit http://homepilot/files/img.png")
            assert "remove background" in payload["message"]
            return {"media": {"images": ["http://homepilot/files/out.png"]}}

        monkeypatch.setattr(
            homepilot_client.HomePilotClient, "chat", fake_chat
        )

        response = client.post(
            "/chat",
            json={
                "mode": "edit",
                "conversation_id": "c1",
                "message": "remove background"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["media"]["images"][0].endswith("out.png")

    def test_proxy_chat_passes_through_when_url_present(
        self, client, store, monkeypatch
    ):
        """Chat passes through unchanged when message already contains URL."""
        # Set active image
        store.set_active("c1", "http://homepilot/files/active.png")

        async def fake_chat(self, payload):
            # Message should NOT be rewritten
            assert "http://other/image.png" in payload["message"]
            assert "active.png" not in payload["message"]
            return {"media": {"images": ["http://homepilot/files/out.png"]}}

        monkeypatch.setattr(
            homepilot_client.HomePilotClient, "chat", fake_chat
        )

        response = client.post(
            "/chat",
            json={
                "mode": "edit",
                "conversation_id": "c1",
                "message": "edit http://other/image.png make it red"
            }
        )

        assert response.status_code == 200

    def test_proxy_chat_fails_without_active_image(self, client, monkeypatch):
        """Edit fails with 400 if no active image set."""
        # Don't set any active image

        response = client.post(
            "/chat",
            json={
                "mode": "edit",
                "conversation_id": "new-conversation",
                "message": "remove background"
            }
        )

        assert response.status_code == 400
        assert "No active image" in response.json()["detail"]

    def test_proxy_chat_non_edit_mode_passes_through(
        self, client, store, monkeypatch
    ):
        """Non-edit mode passes through without modification."""
        async def fake_chat(self, payload):
            assert payload["mode"] == "chat"
            assert payload["message"] == "Hello, how are you?"
            return {"text": "I'm doing well!"}

        monkeypatch.setattr(
            homepilot_client.HomePilotClient, "chat", fake_chat
        )

        response = client.post(
            "/chat",
            json={
                "mode": "chat",
                "conversation_id": "c1",
                "message": "Hello, how are you?"
            }
        )

        assert response.status_code == 200
        assert response.json()["text"] == "I'm doing well!"


class TestSessionEndpoints:
    """Test suite for session management endpoints."""

    def test_get_session_returns_state(self, client, store):
        """GET session endpoint returns current state."""
        store.set_active("c1", "http://example.com/a.png")

        response = client.get("/v1/edit-sessions/c1")

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "c1"
        assert data["active_image_url"] == "http://example.com/a.png"

    def test_delete_session_clears_data(self, client, store):
        """DELETE session endpoint clears all data."""
        store.set_active("c1", "http://example.com/a.png")

        response = client.delete("/v1/edit-sessions/c1")

        assert response.status_code == 200
        assert response.json()["ok"] is True

        # Verify cleared
        rec = store.get("c1")
        assert rec.active_image_url is None

    def test_select_image_updates_active(self, client, store, monkeypatch):
        """Select endpoint updates active image."""
        # Set initial active
        store.set_active("c1", "http://backend:8000/files/old.png")

        # Mock settings to allow localhost
        from app import config
        original_url = config.settings.HOME_PILOT_BASE_URL
        config.settings.HOME_PILOT_BASE_URL = "http://backend:8000"

        try:
            response = client.post(
                "/v1/edit-sessions/c1/select",
                json={"image_url": "http://backend:8000/files/new.png"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["active_image_url"] == "http://backend:8000/files/new.png"
        finally:
            config.settings.HOME_PILOT_BASE_URL = original_url

    def test_select_image_rejects_external_url(self, client, store):
        """Select endpoint rejects URLs from disallowed hosts."""
        store.set_active("c1", "http://localhost:8000/files/old.png")

        response = client.post(
            "/v1/edit-sessions/c1/select",
            json={"image_url": "http://evil.com/malicious.png"}
        )

        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_get_history_returns_images(self, client, store):
        """History endpoint returns all images in order."""
        store.set_active("c1", "http://example.com/a.png")
        store.push_history("c1", "http://example.com/b.png")
        store.push_history("c1", "http://example.com/c.png")

        response = client.get("/v1/edit-sessions/c1/history")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert "http://example.com/c.png" in data["history"]

    def test_revert_to_history(self, client, store):
        """Revert endpoint sets previous image as active."""
        store.set_active("c1", "http://example.com/a.png")
        store.set_active("c1", "http://example.com/b.png")
        store.set_active("c1", "http://example.com/c.png")

        # Revert to index 2 (oldest)
        response = client.post(
            "/v1/edit-sessions/c1/revert",
            params={"index": 2}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["active_image_url"] == "http://example.com/a.png"

    def test_revert_invalid_index_fails(self, client, store):
        """Revert with invalid index returns 400."""
        store.set_active("c1", "http://example.com/a.png")

        response = client.post(
            "/v1/edit-sessions/c1/revert",
            params={"index": 10}
        )

        assert response.status_code == 400
        assert "Invalid history index" in response.json()["detail"]
