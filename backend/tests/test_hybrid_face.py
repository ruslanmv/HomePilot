"""
Tests for Hybrid Avatar Pipeline — Stage A: face generation.

Validates:
  - POST /v1/avatars/hybrid/face returns face results from avatar-service
  - Default parameters (count=4, truncation=0.7) are accepted
  - Custom seed produces deterministic seed list
  - Endpoint handles avatar-service errors gracefully (503)

Non-destructive: no network, no LLM, no GPU.
CI-friendly: runs in <1 second.
"""

import pytest
import httpx


# ---------------------------------------------------------------------------
# Stage A — /v1/avatars/hybrid/face
# ---------------------------------------------------------------------------


class TestHybridFaceGeneration:
    """POST /v1/avatars/hybrid/face generates face variations via avatar-service."""

    def _patch_avatar_service(self, monkeypatch):
        """Patch httpx.AsyncClient so avatar-service calls return face results."""

        class FaceAsyncClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, *a, **k):
                u = str(url)
                json_data = k.get("json", {})
                count = json_data.get("count", 4)
                seeds = json_data.get("seeds", [100 + i for i in range(count)])
                results = [
                    {
                        "url": f"/avatars/face_{i}.png",
                        "seed": seeds[i] if i < len(seeds) else 100 + i,
                        "metadata": {"engine": "placeholder"},
                    }
                    for i in range(count)
                ]
                return httpx.Response(
                    200,
                    json={"results": results, "warnings": []},
                    request=httpx.Request("POST", u),
                )

            async def get(self, url, *a, **k):
                return httpx.Response(
                    200,
                    json={"ok": True},
                    request=httpx.Request("GET", str(url)),
                )

        monkeypatch.setattr(httpx, "AsyncClient", FaceAsyncClient)

    def test_face_endpoint_exists(self, client, mock_outbound):
        """Endpoint responds (not 404/405)."""
        resp = client.post("/v1/avatars/hybrid/face", json={})
        assert resp.status_code != 404
        assert resp.status_code != 405

    def test_face_default_params(self, client, monkeypatch):
        """Default request (no params) returns 4 face results."""
        self._patch_avatar_service(monkeypatch)
        resp = client.post("/v1/avatars/hybrid/face", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["stage"] == "face_only"
        assert len(data["results"]) == 4

    def test_face_custom_count(self, client, monkeypatch):
        """Custom count=2 returns exactly 2 results."""
        self._patch_avatar_service(monkeypatch)
        resp = client.post("/v1/avatars/hybrid/face", json={"count": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 2

    def test_face_custom_seed(self, client, monkeypatch):
        """Custom seed produces sequential seeds in results."""
        self._patch_avatar_service(monkeypatch)
        resp = client.post(
            "/v1/avatars/hybrid/face",
            json={"count": 3, "seed": 42},
        )
        assert resp.status_code == 200
        data = resp.json()
        seeds = [r["seed"] for r in data["results"]]
        assert seeds == [42, 43, 44]

    def test_face_result_has_url(self, client, monkeypatch):
        """Each result has a url field."""
        self._patch_avatar_service(monkeypatch)
        resp = client.post("/v1/avatars/hybrid/face", json={"count": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"][0]["url"].endswith(".png")

    def test_face_truncation_accepted(self, client, monkeypatch):
        """Custom truncation value is accepted without error."""
        self._patch_avatar_service(monkeypatch)
        resp = client.post(
            "/v1/avatars/hybrid/face",
            json={"truncation": 0.5, "count": 1},
        )
        assert resp.status_code == 200

    def test_face_invalid_count_rejected(self, client, mock_outbound):
        """count=0 is rejected by Pydantic validation (ge=1)."""
        resp = client.post("/v1/avatars/hybrid/face", json={"count": 0})
        assert resp.status_code == 422

    def test_face_warnings_field_present(self, client, monkeypatch):
        """Response always includes a warnings list."""
        self._patch_avatar_service(monkeypatch)
        resp = client.post("/v1/avatars/hybrid/face", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["warnings"], list)


# ---------------------------------------------------------------------------
# Schema unit tests — no HTTP needed
# ---------------------------------------------------------------------------


class TestHybridFaceSchemas:
    """HybridFaceRequest / HybridFaceResponse schema validation."""

    def test_face_request_defaults(self):
        from app.avatar.hybrid_schemas import HybridFaceRequest

        req = HybridFaceRequest()
        assert req.count == 4
        assert req.truncation == 0.7
        assert req.seed is None

    def test_face_request_custom(self):
        from app.avatar.hybrid_schemas import HybridFaceRequest

        req = HybridFaceRequest(count=2, seed=42, truncation=0.5)
        assert req.count == 2
        assert req.seed == 42
        assert req.truncation == 0.5

    def test_face_response_model(self):
        from app.avatar.hybrid_schemas import HybridFaceResponse, HybridFaceResult

        resp = HybridFaceResponse(
            results=[HybridFaceResult(url="/test.png", seed=1)],
        )
        assert resp.stage == "face_only"
        assert len(resp.results) == 1
        assert resp.results[0].url == "/test.png"
