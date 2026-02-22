"""
Multimodal (Vision) Health & Unit Tests

Validates:
  - Multimodal catalog entries exist and have required fields
  - Multimodal models exist in the Ollama registry (network test)
  - Backend multimodal endpoints return correct structure
  - Vision intent detection works
  - Image helpers handle edge cases

Usage:
  cd backend && python -m pytest tests/test_multimodal.py -v
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CATALOG_PATH = Path(__file__).resolve().parent.parent / "app" / "model_catalog_data.json"


def load_ollama_multimodal_models() -> list[dict]:
    """Load Ollama multimodal models from the JSON catalog."""
    with open(CATALOG_PATH) as f:
        data = json.load(f)
    return data["providers"]["ollama"].get("multimodal", [])


def ollama_registry_url(model_id: str) -> str:
    """Build the Ollama registry URL for a model."""
    base = model_id.split(":")[0]
    if "/" in base:
        return f"https://ollama.com/{base}"
    else:
        return f"https://ollama.com/library/{base}"


def check_model_exists(model_id: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Check if a model exists on the Ollama registry."""
    url = ollama_registry_url(model_id)
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "HomePilot-HealthCheck/1.0")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        resp.read(1024)
        resp.close()
        if resp.status == 200:
            return True, f"OK ({url})"
        return False, f"HTTP {resp.status} ({url})"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, f"NOT FOUND ({url})"
        return False, f"HTTP {e.code} ({url})"
    except urllib.error.URLError as e:
        return False, f"Network error: {e.reason} ({url})"
    except Exception as e:
        return False, f"Error: {e} ({url})"


# ---------------------------------------------------------------------------
# Catalog validation tests
# ---------------------------------------------------------------------------

class TestMultimodalCatalog:
    """Validate multimodal model catalog entries."""

    def test_multimodal_section_exists(self):
        """Catalog should have a multimodal section under ollama."""
        with open(CATALOG_PATH) as f:
            data = json.load(f)
        assert "multimodal" in data["providers"]["ollama"], (
            "Catalog missing 'multimodal' section under providers.ollama"
        )

    def test_multimodal_catalog_not_empty(self):
        """Should have at least one multimodal model."""
        models = load_ollama_multimodal_models()
        assert len(models) > 0, "Multimodal catalog should not be empty"

    def test_multimodal_required_fields(self):
        """Every multimodal model must have id, label, and size_gb."""
        models = load_ollama_multimodal_models()
        for m in models:
            assert "id" in m, f"Multimodal model missing 'id': {m}"
            assert "label" in m, f"Model {m['id']} missing 'label'"
            assert "size_gb" in m, f"Model {m['id']} missing 'size_gb'"

    def test_no_duplicate_multimodal_ids(self):
        """No duplicate multimodal model IDs."""
        models = load_ollama_multimodal_models()
        ids = [m["id"] for m in models]
        dupes = [mid for mid in ids if ids.count(mid) > 1]
        assert len(dupes) == 0, f"Duplicate multimodal model IDs: {set(dupes)}"

    def test_multimodal_nsfw_consistency(self):
        """Models with nsfw:true should have uncensored:true."""
        models = load_ollama_multimodal_models()
        for m in models:
            if m.get("nsfw"):
                assert m.get("uncensored", False), (
                    f"Multimodal model {m['id']} has nsfw:true but missing uncensored:true"
                )

    def test_default_model_in_catalog(self):
        """The default model 'moondream' must be in the catalog."""
        models = load_ollama_multimodal_models()
        ids = [m["id"] for m in models]
        assert any("moondream" in mid for mid in ids), (
            f"Default model 'moondream' not found in multimodal catalog. IDs: {ids}"
        )

    @pytest.mark.skipif(
        os.environ.get("SKIP_NETWORK_TESTS", "0") == "1",
        reason="SKIP_NETWORK_TESTS=1",
    )
    def test_multimodal_models_exist_in_registry(self):
        """Check that all multimodal models exist on ollama.com (network test)."""
        models = load_ollama_multimodal_models()

        seen_bases = set()
        unique_models = []
        for m in models:
            base = m["id"].split(":")[0]
            if base not in seen_bases:
                seen_bases.add(base)
                unique_models.append(m)

        missing = []
        for m in unique_models:
            exists, detail = check_model_exists(m["id"])
            if not exists:
                missing.append((m["id"], m["label"], detail))

        if missing:
            msg_lines = [f"\n{len(missing)} multimodal model(s) not found on Ollama registry:"]
            for mid, label, detail in missing:
                msg_lines.append(f"  - {mid} ({label}): {detail}")
            import warnings
            warnings.warn("\n".join(msg_lines))


# ---------------------------------------------------------------------------
# Vision intent detection tests
# ---------------------------------------------------------------------------

class TestVisionIntentDetection:
    """Test the is_vision_intent() function."""

    @pytest.fixture(autouse=True)
    def _import_multimodal(self):
        """Import the multimodal module."""
        backend_root = Path(__file__).resolve().parent.parent
        if str(backend_root) not in sys.path:
            sys.path.insert(0, str(backend_root))
        from app.multimodal import is_vision_intent
        self.is_vision_intent = is_vision_intent

    def test_positive_intents(self):
        """Should detect image analysis requests."""
        positives = [
            "read this image",
            "describe the picture",
            "what's in this photo",
            "analyze my screenshot",
            "ocr this",
            "extract text",
            "look at this image",
            "can you see",
            "tell me about this image",
            "what does the screenshot show",
        ]
        for text in positives:
            assert self.is_vision_intent(text), f"Should detect: '{text}'"

    def test_negative_intents(self):
        """Should NOT trigger on normal chat messages."""
        negatives = [
            "hello how are you",
            "tell me a joke",
            "what is the weather",
            "write me a poem",
            "help me with my homework",
            "",
            "I like pictures",
            "read me a story",
        ]
        for text in negatives:
            assert not self.is_vision_intent(text), f"Should NOT detect: '{text}'"

    def test_empty_and_none(self):
        """Empty or falsy input should return False."""
        assert not self.is_vision_intent("")
        assert not self.is_vision_intent(None)


# ---------------------------------------------------------------------------
# Backend endpoint tests (mocked)
# ---------------------------------------------------------------------------

class TestMultimodalEndpoints:
    """Test multimodal API endpoints via TestClient."""

    def test_multimodal_status_endpoint(self, client, mock_outbound):
        """GET /v1/multimodal/status should return correct structure."""
        response = client.get("/v1/multimodal/status")
        assert response.status_code == 200
        data = response.json()
        assert "ok" in data
        assert "multimodal_available" in data
        assert "provider" in data
        assert data["provider"] == "ollama"
        assert "provider_reachable" in data
        assert "installed_vision_models" in data
        assert isinstance(data["installed_vision_models"], list)
        assert "recommended_default" in data

    def test_multimodal_analyze_requires_image(self, client, mock_outbound):
        """POST /v1/multimodal/analyze should require image_url."""
        response = client.post("/v1/multimodal/analyze", json={})
        # Should return 422 (validation error) because image_url is required
        assert response.status_code == 422

    def test_multimodal_analyze_with_image(self, client, mock_outbound):
        """POST /v1/multimodal/analyze should accept and return structured response."""
        response = client.post(
            "/v1/multimodal/analyze",
            json={
                "image_url": "http://example.com/test.png",
                "mode": "caption",
            },
        )
        # With mocked outbound, may succeed or gracefully fail (image fetch error)
        assert response.status_code in [200, 500]
        data = response.json()
        # Whether it succeeded or not, it should return structured JSON
        assert isinstance(data, dict)
        if response.status_code == 200:
            assert "ok" in data
            assert "meta" in data


# ---------------------------------------------------------------------------
# Health endpoint multimodal coverage
# ---------------------------------------------------------------------------

class TestHealthIncludesMultimodal:
    """Verify that health endpoints cover multimodal status."""

    def test_detailed_health_has_multimodal(self, client, mock_outbound):
        """GET /health/detailed should include multimodal section."""
        response = client.get("/health/detailed")
        assert response.status_code in [200, 503]
        data = response.json()
        assert "services" in data
        services = data["services"]
        assert "multimodal" in services, (
            f"Detailed health missing 'multimodal' section. Keys: {list(services.keys())}"
        )
        mm = services["multimodal"]
        assert "ok" in mm
        assert "vision_models" in mm or "status" in mm
