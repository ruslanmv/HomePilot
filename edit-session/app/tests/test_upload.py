"""
Tests for the upload endpoint.
"""

import pytest
from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app
from app.store import SQLiteStore
from app import homepilot_client
from app import security as security_module


def make_png_bytes(width: int = 100, height: int = 100) -> bytes:
    """Create a valid PNG image for testing."""
    im = Image.new("RGBA", (width, height), color=(255, 0, 0, 255))
    out = BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def make_jpeg_bytes(width: int = 100, height: int = 100) -> bytes:
    """Create a valid JPEG image for testing."""
    im = Image.new("RGB", (width, height), color=(0, 255, 0))
    out = BytesIO()
    im.save(out, format="JPEG")
    return out.getvalue()


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


class TestUploadEndpoint:
    """Test suite for /upload endpoint."""

    def test_upload_rejects_non_image_content_type(self, client):
        """Upload rejects files with non-image content type."""
        response = client.post(
            "/upload",
            files={"file": ("test.txt", b"hello world", "text/plain")},
        )

        assert response.status_code == 400
        assert "Unsupported content type" in response.json()["detail"]

    def test_upload_rejects_empty_file(self, client):
        """Upload rejects empty files."""
        response = client.post(
            "/upload",
            files={"file": ("empty.png", b"", "image/png")},
        )

        assert response.status_code == 400
        assert "Empty upload" in response.json()["detail"]

    def test_upload_rejects_invalid_image_data(self, client):
        """Upload rejects files with wrong content (not actually an image)."""
        response = client.post(
            "/upload",
            files={"file": ("fake.png", b"not an image", "image/png")},
        )

        assert response.status_code == 400
        assert "Invalid image" in response.json()["detail"]

    def test_upload_accepts_valid_png(self, client, monkeypatch):
        """Upload accepts valid PNG images."""
        async def fake_upload(self, filename, content_type, data):
            assert filename == "test.png"
            assert content_type == "image/png"
            assert len(data) > 0
            return "http://homepilot/files/uploaded.png"

        monkeypatch.setattr(
            homepilot_client.HomePilotClient, "upload", fake_upload
        )

        png = make_png_bytes()
        response = client.post(
            "/upload",
            files={"file": ("test.png", png, "image/png")},
        )

        assert response.status_code == 200
        assert response.json()["url"] == "http://homepilot/files/uploaded.png"

    def test_upload_accepts_valid_jpeg(self, client, monkeypatch):
        """Upload accepts valid JPEG images."""
        async def fake_upload(self, filename, content_type, data):
            return "http://homepilot/files/uploaded.jpg"

        monkeypatch.setattr(
            homepilot_client.HomePilotClient, "upload", fake_upload
        )

        jpeg = make_jpeg_bytes()
        response = client.post(
            "/upload",
            files={"file": ("test.jpg", jpeg, "image/jpeg")},
        )

        assert response.status_code == 200
        assert response.json()["url"].endswith(".jpg")

    def test_upload_sets_active_image_with_conversation_id(
        self, client, store, monkeypatch
    ):
        """Upload with conversation_id sets the active image."""
        async def fake_upload(self, filename, content_type, data):
            return "http://homepilot/files/uploaded.png"

        monkeypatch.setattr(
            homepilot_client.HomePilotClient, "upload", fake_upload
        )

        png = make_png_bytes()
        response = client.post(
            "/upload",
            files={"file": ("test.png", png, "image/png")},
            data={"conversation_id": "conv-123"},
        )

        assert response.status_code == 200

        # Verify active image was set
        rec = store.get("conv-123")
        assert rec.active_image_url == "http://homepilot/files/uploaded.png"

    def test_upload_without_conversation_id_does_not_set_active(
        self, client, store, monkeypatch
    ):
        """Upload without conversation_id does not create session."""
        async def fake_upload(self, filename, content_type, data):
            return "http://homepilot/files/uploaded.png"

        monkeypatch.setattr(
            homepilot_client.HomePilotClient, "upload", fake_upload
        )

        png = make_png_bytes()
        response = client.post(
            "/upload",
            files={"file": ("test.png", png, "image/png")},
        )

        assert response.status_code == 200
        # No session should be created
        # (We can't easily verify this without knowing the conversation_id)


class TestSetActiveImageEndpoint:
    """Test suite for /v1/edit-sessions/{id}/image endpoint."""

    def test_set_active_image_basic(self, client, store, monkeypatch):
        """Basic upload and set active image."""
        async def fake_upload(self, filename, content_type, data):
            return "http://homepilot/files/uploaded.png"

        monkeypatch.setattr(
            homepilot_client.HomePilotClient, "upload", fake_upload
        )

        png = make_png_bytes()
        response = client.post(
            "/v1/edit-sessions/conv-456/image",
            files={"file": ("test.png", png, "image/png")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "conv-456"
        assert data["active_image_url"] == "http://homepilot/files/uploaded.png"
        assert "http://homepilot/files/uploaded.png" in data["history"]

    def test_set_active_image_with_instruction(
        self, client, store, monkeypatch
    ):
        """Upload with initial edit instruction."""
        async def fake_upload(self, filename, content_type, data):
            return "http://homepilot/files/uploaded.png"

        async def fake_chat(self, payload):
            assert "remove background" in payload["message"]
            assert payload["mode"] == "edit"
            return {
                "media": {
                    "images": ["http://homepilot/files/result.png"]
                }
            }

        monkeypatch.setattr(
            homepilot_client.HomePilotClient, "upload", fake_upload
        )
        monkeypatch.setattr(
            homepilot_client.HomePilotClient, "chat", fake_chat
        )

        png = make_png_bytes()
        response = client.post(
            "/v1/edit-sessions/conv-789/image",
            files={"file": ("test.png", png, "image/png")},
            data={"instruction": "remove background"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert data["result"]["media"]["images"][0].endswith("result.png")

        # Verify result was added to history
        rec = store.get("conv-789")
        assert "http://homepilot/files/result.png" in rec.history
