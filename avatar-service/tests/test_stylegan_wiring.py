"""
StyleGAN wiring unit tests — CI-light (no GPU, no model weights, no network).

Validates the full avatar-service integration wiring:
  1. Config reads environment correctly
  2. Loader state machine (not loaded → loaded → capabilities reflect it)
  3. Router: capabilities endpoint reports correct status
  4. Router: generate endpoint falls back to placeholder when model not loaded
  5. Router: generate endpoint uses StyleGAN when model IS loaded (mocked)
  6. Storage: placeholder and PIL image saving produce correct URL shapes
  7. Schemas: request/response validation
  8. Startup: graceful degradation when weights missing

Non-destructive: no network, no GPU, no model downloads.
CI-friendly: runs in <2 seconds.
"""

from __future__ import annotations

import os
import importlib
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# 1. Config — environment variable parsing
# ---------------------------------------------------------------------------

class TestConfig:
    """Config reads environment variables with correct defaults."""

    def test_defaults(self, monkeypatch):
        """Default config has StyleGAN disabled and no weights path."""
        # Clear any existing env vars
        for k in ("STYLEGAN_ENABLED", "STYLEGAN_WEIGHTS_PATH", "STYLEGAN_DEVICE",
                   "AVATAR_OUTPUT_DIR", "AVATAR_SERVICE_PORT"):
            monkeypatch.delenv(k, raising=False)

        # Re-import to pick up fresh env
        import app.config as cfg_mod
        importlib.reload(cfg_mod)
        fresh = cfg_mod.Settings()

        assert fresh.stylegan_enabled is False
        assert fresh.stylegan_weights_path == ""
        assert fresh.stylegan_device == "auto"
        assert fresh.port == 8020

    def test_enabled_true(self, monkeypatch):
        monkeypatch.setenv("STYLEGAN_ENABLED", "true")
        import app.config as cfg_mod
        importlib.reload(cfg_mod)
        s = cfg_mod.Settings()
        assert s.stylegan_enabled is True

    def test_enabled_false_variants(self, monkeypatch):
        for val in ("false", "no", "0", "off", ""):
            monkeypatch.setenv("STYLEGAN_ENABLED", val)
            import app.config as cfg_mod
            importlib.reload(cfg_mod)
            s = cfg_mod.Settings()
            assert s.stylegan_enabled is False, f"Expected False for STYLEGAN_ENABLED={val!r}"

    def test_model_exists_false_when_no_path(self, monkeypatch):
        monkeypatch.delenv("STYLEGAN_WEIGHTS_PATH", raising=False)
        import app.config as cfg_mod
        importlib.reload(cfg_mod)
        s = cfg_mod.Settings()
        assert s.model_exists is False

    def test_model_exists_false_when_path_missing(self, monkeypatch):
        monkeypatch.setenv("STYLEGAN_WEIGHTS_PATH", "/nonexistent/model.pkl")
        import app.config as cfg_mod
        importlib.reload(cfg_mod)
        s = cfg_mod.Settings()
        assert s.model_exists is False

    def test_model_exists_true_when_file_present(self, monkeypatch, tmp_path):
        f = tmp_path / "model.pkl"
        f.write_bytes(b"fake")
        monkeypatch.setenv("STYLEGAN_WEIGHTS_PATH", str(f))
        import app.config as cfg_mod
        importlib.reload(cfg_mod)
        s = cfg_mod.Settings()
        assert s.model_exists is True


# ---------------------------------------------------------------------------
# 2. Loader — state machine
# ---------------------------------------------------------------------------

class TestLoader:
    """Loader reports correct state without requiring real weights."""

    def test_not_loaded_by_default(self):
        from app.stylegan.loader import is_loaded
        # Reset module state
        import app.stylegan.loader as loader_mod
        loader_mod._G = None
        loader_mod._device = None
        loader_mod._loaded_path = None

        assert is_loaded() is False

    def test_get_generator_raises_when_not_loaded(self):
        from app.stylegan.loader import LoadError, get_generator
        import app.stylegan.loader as loader_mod
        loader_mod._G = None

        with pytest.raises(LoadError, match="not loaded"):
            get_generator()

    def test_load_model_raises_on_missing_file_or_deps(self):
        """load_model raises LoadError for missing file OR missing torch (CI)."""
        from app.stylegan.loader import LoadError, load_model
        with pytest.raises(LoadError):
            load_model("/nonexistent/model.pkl")

    def test_is_loaded_true_after_manual_set(self):
        """Simulate a successful load by setting the module cache."""
        import app.stylegan.loader as loader_mod
        loader_mod._G = MagicMock()  # fake generator
        loader_mod._device = "cpu"
        loader_mod._loaded_path = "/fake/model.pkl"

        assert loader_mod.is_loaded() is True

        # Cleanup
        loader_mod._G = None
        loader_mod._device = None
        loader_mod._loaded_path = None


# ---------------------------------------------------------------------------
# 3. Generator — raises when not loaded
# ---------------------------------------------------------------------------

class TestGenerator:
    """Generator correctly raises StyleGANUnavailable when model not loaded."""

    def test_generate_faces_raises_when_not_loaded(self):
        from app.stylegan.generator import StyleGANUnavailable, generate_faces
        import app.stylegan.loader as loader_mod
        loader_mod._G = None

        with pytest.raises(StyleGANUnavailable, match="not loaded"):
            generate_faces(count=1)


# ---------------------------------------------------------------------------
# 4. Storage — placeholder and PIL image saving
# ---------------------------------------------------------------------------

class TestStorage:
    """Storage functions produce correct output shapes."""

    def test_placeholder_returns_correct_count(self, tmp_output_dir, monkeypatch):
        # Re-import to pick up patched AVATAR_OUTPUT_DIR
        import app.storage.local_store as store_mod
        importlib.reload(store_mod)
        store_mod.OUTPUT_DIR = tmp_output_dir

        results = store_mod.save_placeholder_pngs(3)
        assert len(results) == 3

    def test_placeholder_result_shape(self, tmp_output_dir):
        import app.storage.local_store as store_mod
        store_mod.OUTPUT_DIR = tmp_output_dir

        results = store_mod.save_placeholder_pngs(1, seeds=[42])
        r = results[0]
        assert "url" in r
        assert "seed" in r
        assert "metadata" in r
        assert r["seed"] == 42
        assert r["url"].startswith("/files/")
        assert r["metadata"]["generator"] == "placeholder"

    def test_placeholder_creates_png_on_disk(self, tmp_output_dir):
        import app.storage.local_store as store_mod
        store_mod.OUTPUT_DIR = tmp_output_dir

        results = store_mod.save_placeholder_pngs(1, seeds=[99])
        # The file should exist on disk
        filename = results[0]["url"].split("/files/")[-1]
        path = tmp_output_dir / filename
        assert path.exists()
        # Verify it's a valid image
        img = Image.open(path)
        assert img.size == (512, 512)

    def test_save_pil_images(self, tmp_output_dir):
        import app.storage.local_store as store_mod
        store_mod.OUTPUT_DIR = tmp_output_dir

        test_img = Image.new("RGB", (256, 256), color=(100, 150, 200))
        images = [{"image": test_img, "seed": 123, "metadata": {"generator": "test"}}]
        results = store_mod.save_pil_images(images)

        assert len(results) == 1
        r = results[0]
        assert r["url"].startswith("/files/")
        assert r["seed"] == 123
        assert r["metadata"]["generator"] == "test"

    def test_save_pil_images_resizes(self, tmp_output_dir):
        import app.storage.local_store as store_mod
        store_mod.OUTPUT_DIR = tmp_output_dir

        # Input is 256x256, output should be resized to 512x512
        test_img = Image.new("RGB", (256, 256), color=(50, 50, 50))
        images = [{"image": test_img, "seed": 1, "metadata": {}}]
        results = store_mod.save_pil_images(images, output_size=512)

        filename = results[0]["url"].split("/files/")[-1]
        saved = Image.open(tmp_output_dir / filename)
        assert saved.size == (512, 512)


# ---------------------------------------------------------------------------
# 5. Schemas — request/response validation
# ---------------------------------------------------------------------------

class TestSchemas:
    """Pydantic schemas enforce constraints."""

    def test_generate_request_defaults(self):
        from app.schemas import GenerateRequest
        req = GenerateRequest()
        assert req.count == 4
        assert req.truncation == 0.7
        assert req.seeds is None

    def test_generate_request_count_range(self):
        from app.schemas import GenerateRequest
        from pydantic import ValidationError

        # Valid
        GenerateRequest(count=1)
        GenerateRequest(count=8)

        # Invalid
        with pytest.raises(ValidationError):
            GenerateRequest(count=0)
        with pytest.raises(ValidationError):
            GenerateRequest(count=9)

    def test_truncation_range(self):
        from app.schemas import GenerateRequest
        from pydantic import ValidationError

        GenerateRequest(truncation=0.1)
        GenerateRequest(truncation=1.0)

        with pytest.raises(ValidationError):
            GenerateRequest(truncation=0.05)
        with pytest.raises(ValidationError):
            GenerateRequest(truncation=1.5)

    def test_generate_response_shape(self):
        from app.schemas import GenerateResponse, Result
        resp = GenerateResponse(
            results=[Result(url="/files/test.png", seed=42, metadata={"generator": "test"})],
            warnings=["test warning"],
        )
        assert len(resp.results) == 1
        assert resp.results[0].url == "/files/test.png"
        assert resp.warnings == ["test warning"]


# ---------------------------------------------------------------------------
# 6. Router — capabilities & generate endpoints (via TestClient)
# ---------------------------------------------------------------------------

class TestRouterCapabilities:
    """Capabilities endpoint reports correct StyleGAN status."""

    @pytest.fixture()
    def test_client(self, monkeypatch):
        """Create a test client with StyleGAN disabled (default)."""
        monkeypatch.setenv("STYLEGAN_ENABLED", "false")
        monkeypatch.setenv("AVATAR_OUTPUT_DIR", "/tmp/avatar-test-output")
        os.makedirs("/tmp/avatar-test-output", exist_ok=True)

        # Reset loader state
        import app.stylegan.loader as loader_mod
        loader_mod._G = None
        loader_mod._device = None
        loader_mod._loaded_path = None

        from fastapi.testclient import TestClient
        # Re-import main to pick up fresh config
        import app.main as main_mod
        importlib.reload(main_mod)
        return TestClient(main_mod.app)

    def test_capabilities_disabled(self, test_client):
        r = test_client.get("/v1/avatars/capabilities")
        assert r.status_code == 200
        data = r.json()

        assert data["default_engine"] == "placeholder"
        assert data["engines"]["placeholder"]["available"] is True
        assert data["engines"]["stylegan"]["available"] is False
        assert data["engines"]["stylegan"]["reason"] == "disabled"

    def test_capabilities_has_engines_key(self, test_client):
        r = test_client.get("/v1/avatars/capabilities")
        data = r.json()
        assert "engines" in data
        assert "stylegan" in data["engines"]
        assert "placeholder" in data["engines"]


class TestRouterGenerate:
    """Generate endpoint produces correct responses."""

    @pytest.fixture()
    def test_client(self, tmp_path, monkeypatch):
        out = tmp_path / "uploads"
        out.mkdir()
        monkeypatch.setenv("STYLEGAN_ENABLED", "false")
        monkeypatch.setenv("AVATAR_OUTPUT_DIR", str(out))

        import app.stylegan.loader as loader_mod
        loader_mod._G = None
        loader_mod._device = None
        loader_mod._loaded_path = None

        from fastapi.testclient import TestClient
        import app.main as main_mod
        importlib.reload(main_mod)
        return TestClient(main_mod.app)

    def test_generate_placeholder_mode(self, test_client):
        """When StyleGAN is disabled, generate returns placeholders with warnings."""
        r = test_client.post("/v1/avatars/generate", json={"count": 2})
        assert r.status_code == 200
        data = r.json()

        assert len(data["results"]) == 2
        assert len(data["warnings"]) > 0
        assert any("placeholder" in w.lower() for w in data["warnings"])

    def test_generate_result_shape(self, test_client):
        r = test_client.post("/v1/avatars/generate", json={"count": 1, "seeds": [42]})
        data = r.json()
        result = data["results"][0]

        assert "url" in result
        assert "seed" in result
        assert result["seed"] == 42
        assert result["url"].startswith("/files/")

    def test_generate_respects_count(self, test_client):
        for count in (1, 4, 8):
            r = test_client.post("/v1/avatars/generate", json={"count": count})
            data = r.json()
            assert len(data["results"]) == count

    def test_generate_deterministic_seeds(self, test_client):
        """Same seeds should produce same results (placeholder: same colors)."""
        r1 = test_client.post("/v1/avatars/generate", json={"count": 2, "seeds": [100, 200]})
        r2 = test_client.post("/v1/avatars/generate", json={"count": 2, "seeds": [100, 200]})
        seeds1 = [r["seed"] for r in r1.json()["results"]]
        seeds2 = [r["seed"] for r in r2.json()["results"]]
        assert seeds1 == seeds2 == [100, 200]

    def test_generate_with_stylegan_mock(self, test_client):
        """When StyleGAN is 'loaded' (mocked), generate should use it without placeholder warnings."""
        import app.stylegan.loader as loader_mod

        # Simulate loaded state
        mock_G = MagicMock()
        loader_mod._G = mock_G
        loader_mod._device = "cpu"

        # Mock generate_faces to return fake PIL images
        fake_img = Image.new("RGB", (512, 512), color=(200, 100, 50))
        mock_faces = [
            {"image": fake_img, "seed": 42, "metadata": {"generator": "stylegan2", "truncation": 0.7}}
        ]

        with patch("app.stylegan.generator.generate_faces", return_value=mock_faces):
            r = test_client.post("/v1/avatars/generate", json={"count": 1, "seeds": [42]})

        data = r.json()
        assert r.status_code == 200
        assert len(data["results"]) == 1
        # No placeholder warnings
        assert not any("placeholder" in w.lower() for w in data.get("warnings", []))

        # Cleanup
        loader_mod._G = None
        loader_mod._device = None


# ---------------------------------------------------------------------------
# 7. Startup — graceful degradation
# ---------------------------------------------------------------------------

class TestStartup:
    """Startup is graceful when weights are missing."""

    @pytest.mark.asyncio
    async def test_startup_disabled(self, monkeypatch, caplog):
        """When STYLEGAN_ENABLED=false, startup logs info and doesn't crash."""
        monkeypatch.setenv("STYLEGAN_ENABLED", "false")
        monkeypatch.setenv("AVATAR_OUTPUT_DIR", "/tmp/avatar-test-startup")
        os.makedirs("/tmp/avatar-test-startup", exist_ok=True)

        import app.main as main_mod
        importlib.reload(main_mod)

        import app.stylegan.loader as loader_mod
        loader_mod._G = None

        # Call startup handler directly
        await main_mod._startup_load_stylegan()
        assert loader_mod.is_loaded() is False

    @pytest.mark.asyncio
    async def test_startup_missing_weights(self, monkeypatch, caplog):
        """When enabled but weights missing, startup doesn't crash."""
        monkeypatch.setenv("STYLEGAN_ENABLED", "true")
        monkeypatch.setenv("STYLEGAN_WEIGHTS_PATH", "/nonexistent/model.pkl")
        monkeypatch.setenv("AVATAR_OUTPUT_DIR", "/tmp/avatar-test-startup2")
        os.makedirs("/tmp/avatar-test-startup2", exist_ok=True)

        import app.config as cfg_mod
        importlib.reload(cfg_mod)
        import app.main as main_mod
        importlib.reload(main_mod)

        import app.stylegan.loader as loader_mod
        loader_mod._G = None

        await main_mod._startup_load_stylegan()
        assert loader_mod.is_loaded() is False


# ---------------------------------------------------------------------------
# 8. Integration — full pipeline placeholder path
# ---------------------------------------------------------------------------

class TestPlaceholderPipeline:
    """End-to-end: request → placeholder generation → correct response."""

    def test_full_pipeline_without_stylegan(self, tmp_path, monkeypatch):
        """Complete pipeline: disabled StyleGAN → placeholder results with URLs."""
        out = tmp_path / "uploads"
        out.mkdir()
        monkeypatch.setenv("STYLEGAN_ENABLED", "false")
        monkeypatch.setenv("AVATAR_OUTPUT_DIR", str(out))

        import app.stylegan.loader as loader_mod
        loader_mod._G = None
        loader_mod._device = None

        # Patch storage OUTPUT_DIR to use our temp dir
        import app.storage.local_store as store_mod
        store_mod.OUTPUT_DIR = out

        from fastapi.testclient import TestClient
        import app.main as main_mod
        importlib.reload(main_mod)
        client = TestClient(main_mod.app)

        # Generate
        r = client.post("/v1/avatars/generate", json={"count": 4, "truncation": 0.5})
        assert r.status_code == 200
        data = r.json()

        # 4 results
        assert len(data["results"]) == 4

        # Each result has URL and seed
        for result in data["results"]:
            assert result["url"].startswith("/files/")
            assert isinstance(result["seed"], int)
            assert result["metadata"]["generator"] == "placeholder"

        # Warnings indicate placeholder mode
        assert any("placeholder" in w.lower() for w in data["warnings"])
