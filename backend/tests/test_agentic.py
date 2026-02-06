"""
Agentic AI layer — health, safety, and integration tests.

These tests verify that the /v1/agentic/* endpoints work correctly,
return the right response shapes, and respect the AGENTIC_ENABLED flag.
All outbound calls are mocked — no real Context Forge or ComfyUI needed.
"""

import os
import pytest


# ---------------------------------------------------------------------------
# 1) Status & admin (Phase 1)
# ---------------------------------------------------------------------------


class TestAgenticStatus:
    """GET /v1/agentic/status — feature-flag + health ping."""

    def test_status_returns_200(self, client):
        resp = client.get("/v1/agentic/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "configured" in data
        assert "reachable" in data
        assert "admin_configured" in data
        assert isinstance(data["enabled"], bool)
        assert isinstance(data["configured"], bool)

    def test_status_shape(self, client):
        data = client.get("/v1/agentic/status").json()
        # All four keys are booleans
        for key in ("enabled", "configured", "reachable", "admin_configured"):
            assert isinstance(data[key], bool), f"{key} should be bool"


class TestAgenticAdmin:
    """GET /v1/agentic/admin — returns admin UI URL."""

    def test_admin_returns_url(self, client):
        resp = client.get("/v1/agentic/admin")
        assert resp.status_code == 200
        data = resp.json()
        assert "admin_url" in data
        assert data["admin_url"].startswith("http")


# ---------------------------------------------------------------------------
# 2) Capabilities (Phase 2–3)
# ---------------------------------------------------------------------------


class TestAgenticCapabilities:
    """GET /v1/agentic/capabilities — dynamic capability list."""

    def test_capabilities_returns_list(self, client):
        resp = client.get("/v1/agentic/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert "capabilities" in data
        assert isinstance(data["capabilities"], list)

    def test_builtin_capabilities_always_present(self, client):
        """generate_images and generate_videos are built-in and always available."""
        data = client.get("/v1/agentic/capabilities").json()
        ids = {c["id"] for c in data["capabilities"]}
        assert "generate_images" in ids, "generate_images should always be present"
        assert "generate_videos" in ids, "generate_videos should always be present"

    def test_capability_shape(self, client):
        data = client.get("/v1/agentic/capabilities").json()
        for cap in data["capabilities"]:
            assert "id" in cap
            assert "label" in cap
            assert "description" in cap
            assert "category" in cap
            assert "available" in cap
            assert isinstance(cap["available"], bool)

    def test_capabilities_includes_source(self, client):
        """Phase 4: capabilities response includes a source field."""
        data = client.get("/v1/agentic/capabilities").json()
        assert "source" in data
        assert data["source"] in ("built_in", "forge", "mixed")


# ---------------------------------------------------------------------------
# 3) Invoke (Phase 3) — safety checks
# ---------------------------------------------------------------------------


class TestAgenticInvokeSafety:
    """POST /v1/agentic/invoke — validate request guards."""

    def test_invoke_rejects_unknown_intent(self, client):
        """Unknown intents should be rejected (403 or 400)."""
        resp = client.post(
            "/v1/agentic/invoke",
            json={
                "intent": "hack_the_planet",
                "args": {"prompt": "test"},
            },
        )
        assert resp.status_code in (400, 403)

    def test_invoke_rejects_empty_prompt(self, client):
        """generate_images requires a non-empty prompt."""
        resp = client.post(
            "/v1/agentic/invoke",
            json={
                "intent": "generate_images",
                "args": {"prompt": ""},
            },
        )
        assert resp.status_code == 400

    def test_invoke_rejects_missing_prompt(self, client):
        """generate_images requires args.prompt."""
        resp = client.post(
            "/v1/agentic/invoke",
            json={
                "intent": "generate_images",
                "args": {},
            },
        )
        assert resp.status_code == 400

    def test_invoke_accepts_valid_profile(self, client, mock_outbound):
        """Valid profiles (fast, balanced, quality) should be accepted."""
        for profile in ("fast", "balanced", "quality"):
            resp = client.post(
                "/v1/agentic/invoke",
                json={
                    "intent": "generate_images",
                    "args": {"prompt": "a red circle"},
                    "profile": profile,
                },
            )
            # Should not fail on profile validation (may fail on ComfyUI mock,
            # but should at least not be a 400/403)
            assert resp.status_code != 403, f"profile {profile} rejected"

    def test_invoke_returns_correct_shape(self, client, mock_outbound):
        """Response must include ok, conversation_id, assistant_text."""
        resp = client.post(
            "/v1/agentic/invoke",
            json={
                "intent": "generate_images",
                "args": {"prompt": "a blue square"},
                "profile": "fast",
            },
        )
        # Even if generation fails internally, the response format should be valid
        data = resp.json()
        assert "ok" in data
        assert "conversation_id" in data
        assert "assistant_text" in data
        assert isinstance(data["ok"], bool)


# ---------------------------------------------------------------------------
# 4) Policy — allowlist enforcement
# ---------------------------------------------------------------------------


class TestAgenticPolicy:
    """Verify the capability allowlist is enforced."""

    ALLOWED = [
        "generate_images",
        "generate_videos",
        "code_analysis",
        "data_analysis",
        "web_search",
        "document_qa",
        "story_generation",
        "agent_chat",
    ]

    BLOCKED = [
        "delete_files",
        "run_shell",
        "admin_override",
        "hack_the_planet",
        "",
    ]

    def test_allowed_intents_accepted(self, client):
        """All allowed intents should not get 403."""
        for intent in self.ALLOWED:
            resp = client.post(
                "/v1/agentic/invoke",
                json={"intent": intent, "args": {"prompt": "test"}},
            )
            assert resp.status_code != 403, f"{intent} should be allowed"

    def test_blocked_intents_rejected(self, client):
        """Unlisted intents should get 403."""
        for intent in self.BLOCKED:
            if not intent:
                continue  # empty string handled elsewhere
            resp = client.post(
                "/v1/agentic/invoke",
                json={"intent": intent, "args": {"prompt": "test"}},
            )
            assert resp.status_code == 403, f"{intent} should be blocked"


# ---------------------------------------------------------------------------
# 5) Endpoint isolation — agentic disabled
# ---------------------------------------------------------------------------


class TestAgenticDisabled:
    """When AGENTIC_ENABLED=false, invoke should return 503."""

    def test_invoke_returns_503_when_disabled(self, client, monkeypatch):
        """If agentic is disabled at runtime, invoke returns 503."""
        # Patch the module-level flag in routes.py
        import app.agentic.routes as routes_mod
        monkeypatch.setattr(routes_mod, "_ENABLED", False)

        resp = client.post(
            "/v1/agentic/invoke",
            json={"intent": "generate_images", "args": {"prompt": "test"}},
        )
        assert resp.status_code == 503

        # Capabilities should return empty list
        resp = client.get("/v1/agentic/capabilities")
        assert resp.status_code == 200
        assert resp.json()["capabilities"] == []

        # Status should show enabled=False
        resp = client.get("/v1/agentic/status")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
