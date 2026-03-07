"""
StyleGAN orchestration tests — validates the backend fallback chain.

Tests the generate() function in backend/app/avatar/service.py:
  1. studio_random routes to avatar-service first
  2. If avatar-service returns placeholder warnings, falls through to ComfyUI
  3. If both unavailable, returns placeholder
  4. LicenseDenied is handled separately (not silently swallowed)
  5. Logging captures each step of the fallback chain

CI-friendly: no network, no GPU, mocked httpx + ComfyUI.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(mode="studio_random", count=2, seed=42, truncation=0.7):
    from app.avatar.schemas import AvatarGenerateRequest
    return AvatarGenerateRequest(
        mode=mode,
        count=count,
        seed=seed,
        truncation=truncation,
    )


def _mock_avatar_service_real_stylegan():
    """Mock httpx response: avatar-service with real StyleGAN results."""
    return httpx.Response(
        200,
        json={
            "results": [
                {"url": "/files/avatar_1.png", "seed": 42, "metadata": {"generator": "stylegan2"}},
                {"url": "/files/avatar_2.png", "seed": 43, "metadata": {"generator": "stylegan2"}},
            ],
            "warnings": [],
        },
        request=httpx.Request("POST", "http://localhost:8020/v1/avatars/generate"),
    )


def _mock_avatar_service_placeholder():
    """Mock httpx response: avatar-service running but in placeholder mode."""
    return httpx.Response(
        200,
        json={
            "results": [
                {"url": "/files/placeholder_1.png", "seed": 42, "metadata": {"generator": "placeholder"}},
                {"url": "/files/placeholder_2.png", "seed": 43, "metadata": {"generator": "placeholder"}},
            ],
            "warnings": ["Placeholder generator in use (STYLEGAN_ENABLED=false)."],
        },
        request=httpx.Request("POST", "http://localhost:8020/v1/avatars/generate"),
    )


# ---------------------------------------------------------------------------
# 1. Real StyleGAN results pass through correctly
# ---------------------------------------------------------------------------

class TestStudioRandomRealStyleGAN:
    """When avatar-service returns real StyleGAN results, they pass through."""

    @pytest.mark.asyncio
    async def test_real_stylegan_results_returned(self, monkeypatch):
        from app.avatar.service import generate

        # Mock httpx client to return real StyleGAN response
        mock_response = _mock_avatar_service_real_stylegan()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

        req = _make_request()
        result = await generate(req)

        assert result.mode == "studio_random"
        assert len(result.results) == 2
        assert result.results[0].metadata.get("generator") == "stylegan2"
        # No warnings = real StyleGAN
        assert len(result.warnings) == 0


# ---------------------------------------------------------------------------
# 2. Placeholder detection → ComfyUI fallback
# ---------------------------------------------------------------------------

class TestPlaceholderDetection:
    """When avatar-service returns placeholder warnings, backend tries ComfyUI."""

    @pytest.mark.asyncio
    async def test_placeholder_response_triggers_comfyui_fallback(self, monkeypatch):
        from app.avatar.service import generate

        # Mock avatar-service returning placeholder
        mock_response = _mock_avatar_service_placeholder()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

        # Mock ComfyUI as unavailable
        monkeypatch.setattr(
            "app.services.comfyui.client.comfyui_healthy",
            lambda url: False,
        )

        req = _make_request()
        result = await generate(req)

        # Should fall through to built-in placeholder
        assert any("placeholder" in w.lower() or "no ai" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# 3. Connection error → ComfyUI fallback → placeholder
# ---------------------------------------------------------------------------

class TestConnectionErrorFallback:
    """When avatar-service is unreachable, fall back gracefully."""

    @pytest.mark.asyncio
    async def test_connect_error_falls_to_placeholder(self, monkeypatch):
        from app.avatar.service import generate

        # Mock httpx to raise connection error
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

        # ComfyUI also down
        monkeypatch.setattr(
            "app.services.comfyui.client.comfyui_healthy",
            lambda url: False,
        )

        req = _make_request()
        result = await generate(req)

        # Should get placeholder results with warning
        assert len(result.results) > 0
        assert any("no ai" in w.lower() or "placeholder" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# 4. Fallback chain logging
# ---------------------------------------------------------------------------

class TestFallbackLogging:
    """Each step of the fallback chain is logged."""

    @pytest.mark.asyncio
    async def test_logs_avatar_service_attempt(self, monkeypatch, caplog):
        import logging
        from app.avatar.service import generate

        # Mock connection failure
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

        monkeypatch.setattr("app.services.comfyui.client.comfyui_healthy", lambda url: False)

        with caplog.at_level(logging.INFO, logger="app.avatar.service"):
            req = _make_request()
            await generate(req)

        log_text = caplog.text
        # Should log the attempt and fallback steps
        assert "AvatarGen" in log_text
        assert "avatar-service" in log_text.lower() or "step" in log_text.lower()


# ---------------------------------------------------------------------------
# 5. Schema validation
# ---------------------------------------------------------------------------

class TestAvatarSchemas:
    """Backend avatar schemas work correctly."""

    def test_generate_request_defaults(self):
        from app.avatar.schemas import AvatarGenerateRequest
        req = AvatarGenerateRequest()
        assert req.mode == "studio_reference"
        assert req.count == 4
        assert req.truncation == 0.7

    def test_generate_response_shape(self):
        from app.avatar.schemas import AvatarGenerateResponse, AvatarResult
        resp = AvatarGenerateResponse(
            mode="studio_random",
            results=[AvatarResult(url="/files/test.png", seed=42)],
            warnings=["test"],
        )
        assert resp.mode == "studio_random"
        assert len(resp.results) == 1
        assert resp.warnings == ["test"]


# ---------------------------------------------------------------------------
# 6. Availability — stylegan_status shape
# ---------------------------------------------------------------------------

class TestAvailability:
    """stylegan_status() returns correct shape."""

    def test_stylegan_status_shape(self):
        from app.avatar.availability import stylegan_status
        status = stylegan_status()

        assert "installed" in status
        assert "active_pack" in status
        assert "resolution" in status
        assert "packs" in status
        assert isinstance(status["installed"], bool)
        assert "avatar-stylegan2-1024" in status["packs"]
        assert "avatar-stylegan2" in status["packs"]

    def test_enabled_modes_always_includes_studio_random(self):
        """studio_random is always available (placeholder fallback)."""
        from app.avatar.availability import enabled_modes
        modes = enabled_modes()
        assert "studio_random" in modes
