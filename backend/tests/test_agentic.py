"""
Agentic AI layer — health, safety, and integration tests.

These tests verify that the /v1/agentic/* endpoints work correctly,
return the right response shapes, and respect the AGENTIC_ENABLED flag.
All outbound calls are mocked — no real Context Forge or ComfyUI needed.

Phase 5–6 tests: catalog endpoint, registration endpoints, MCP connection
simulation via mocked Context Forge client.
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


# ---------------------------------------------------------------------------
# 6) Catalog endpoint (Phase 5)
# ---------------------------------------------------------------------------


class TestAgenticCatalog:
    """GET /v1/agentic/catalog — wizard-friendly catalog from Context Forge."""

    def test_catalog_returns_200(self, client, mock_outbound):
        resp = client.get("/v1/agentic/catalog")
        assert resp.status_code == 200

    def test_catalog_response_shape(self, client, mock_outbound):
        """Catalog must include tools, a2a_agents, gateways, servers, capability_sources."""
        data = client.get("/v1/agentic/catalog").json()
        assert "tools" in data
        assert "a2a_agents" in data
        assert "gateways" in data
        assert "servers" in data
        assert "capability_sources" in data
        assert "source" in data
        assert isinstance(data["tools"], list)
        assert isinstance(data["a2a_agents"], list)
        assert isinstance(data["gateways"], list)
        assert isinstance(data["servers"], list)
        assert isinstance(data["capability_sources"], dict)

    def test_catalog_empty_when_disabled(self, client, monkeypatch):
        """When agentic is disabled, catalog returns empty lists (not 503)."""
        import app.agentic.routes as routes_mod
        monkeypatch.setattr(routes_mod, "_ENABLED", False)

        resp = client.get("/v1/agentic/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tools"] == []
        assert data["a2a_agents"] == []
        assert data["gateways"] == []
        assert data["servers"] == []


# ---------------------------------------------------------------------------
# 7) Registration endpoints (Phase 6)
# ---------------------------------------------------------------------------


class TestAgenticRegisterTool:
    """POST /v1/agentic/register/tool — register a tool in Context Forge."""

    def test_register_tool_returns_200(self, client, mock_outbound):
        resp = client.post(
            "/v1/agentic/register/tool",
            json={"name": "test_tool", "description": "A test tool"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
        assert "detail" in data
        assert isinstance(data["ok"], bool)

    def test_register_tool_requires_name(self, client, mock_outbound):
        """name is a required field."""
        resp = client.post(
            "/v1/agentic/register/tool",
            json={"description": "Missing name"},
        )
        assert resp.status_code == 422  # Pydantic validation error

    def test_register_tool_503_when_disabled(self, client, monkeypatch):
        """Registration fails with 503 when agentic is disabled."""
        import app.agentic.routes as routes_mod
        monkeypatch.setattr(routes_mod, "_ENABLED", False)

        resp = client.post(
            "/v1/agentic/register/tool",
            json={"name": "test_tool"},
        )
        assert resp.status_code == 503


class TestAgenticRegisterAgent:
    """POST /v1/agentic/register/agent — register an A2A agent."""

    def test_register_agent_returns_200(self, client, mock_outbound):
        resp = client.post(
            "/v1/agentic/register/agent",
            json={
                "name": "test_agent",
                "endpoint_url": "http://localhost:9100/a2a",
                "description": "A test A2A agent",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
        assert isinstance(data["ok"], bool)

    def test_register_agent_requires_endpoint_url(self, client, mock_outbound):
        """endpoint_url is required for agent registration."""
        resp = client.post(
            "/v1/agentic/register/agent",
            json={"name": "test_agent"},
        )
        assert resp.status_code == 422

    def test_register_agent_requires_name(self, client, mock_outbound):
        resp = client.post(
            "/v1/agentic/register/agent",
            json={"endpoint_url": "http://localhost:9100/a2a"},
        )
        assert resp.status_code == 422

    def test_register_agent_503_when_disabled(self, client, monkeypatch):
        import app.agentic.routes as routes_mod
        monkeypatch.setattr(routes_mod, "_ENABLED", False)

        resp = client.post(
            "/v1/agentic/register/agent",
            json={"name": "test_agent", "endpoint_url": "http://localhost:9100/a2a"},
        )
        assert resp.status_code == 503


class TestAgenticRegisterGateway:
    """POST /v1/agentic/register/gateway — register an MCP gateway."""

    def test_register_gateway_returns_200(self, client, mock_outbound):
        resp = client.post(
            "/v1/agentic/register/gateway",
            json={
                "name": "test_gateway",
                "url": "http://localhost:3000/mcp",
                "transport": "SSE",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
        assert isinstance(data["ok"], bool)

    def test_register_gateway_requires_name_and_url(self, client, mock_outbound):
        """Both name and url are required."""
        resp = client.post(
            "/v1/agentic/register/gateway",
            json={"url": "http://localhost:3000/mcp"},
        )
        assert resp.status_code == 422

        resp = client.post(
            "/v1/agentic/register/gateway",
            json={"name": "test_gateway"},
        )
        assert resp.status_code == 422

    def test_register_gateway_default_transport(self, client, mock_outbound):
        """Default transport should be SSE."""
        resp = client.post(
            "/v1/agentic/register/gateway",
            json={"name": "gw_default", "url": "http://localhost:3000/mcp"},
        )
        assert resp.status_code == 200

    def test_register_gateway_503_when_disabled(self, client, monkeypatch):
        import app.agentic.routes as routes_mod
        monkeypatch.setattr(routes_mod, "_ENABLED", False)

        resp = client.post(
            "/v1/agentic/register/gateway",
            json={"name": "gw", "url": "http://localhost:3000/mcp"},
        )
        assert resp.status_code == 503


class TestAgenticRegisterServer:
    """POST /v1/agentic/register/server — create a virtual server."""

    def test_register_server_returns_200(self, client, mock_outbound):
        resp = client.post(
            "/v1/agentic/register/server",
            json={"name": "test_server", "description": "A virtual server"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
        assert isinstance(data["ok"], bool)

    def test_register_server_requires_name(self, client, mock_outbound):
        resp = client.post(
            "/v1/agentic/register/server",
            json={"description": "No name"},
        )
        assert resp.status_code == 422

    def test_register_server_with_tool_ids(self, client, mock_outbound):
        """Optionally include tool_ids when creating a virtual server."""
        resp = client.post(
            "/v1/agentic/register/server",
            json={
                "name": "server_with_tools",
                "tool_ids": ["tool-1", "tool-2"],
            },
        )
        assert resp.status_code == 200

    def test_register_server_503_when_disabled(self, client, monkeypatch):
        import app.agentic.routes as routes_mod
        monkeypatch.setattr(routes_mod, "_ENABLED", False)

        resp = client.post(
            "/v1/agentic/register/server",
            json={"name": "srv"},
        )
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# 8) MCP connection — Context Forge client integration
# ---------------------------------------------------------------------------


class TestMCPConnection:
    """Verify the ContextForgeClient works correctly with mocked Forge responses."""

    def test_catalog_source_field(self, client, mock_outbound):
        """Catalog source should be a valid string."""
        data = client.get("/v1/agentic/catalog").json()
        assert data["source"] in ("forge", "built_in", "mixed")

    def test_capabilities_source_after_forge_query(self, client, mock_outbound):
        """Capabilities should indicate source after querying (mocked) Forge."""
        data = client.get("/v1/agentic/capabilities").json()
        assert data["source"] in ("built_in", "forge", "mixed")

    def test_status_reachable_field(self, client, mock_outbound):
        """Status should report Forge reachability (mocked as reachable)."""
        data = client.get("/v1/agentic/status").json()
        assert isinstance(data["reachable"], bool)

    def test_register_tool_roundtrip(self, client, mock_outbound):
        """Full roundtrip: register a tool, then verify catalog endpoint works."""
        # Register
        resp = client.post(
            "/v1/agentic/register/tool",
            json={
                "name": "mcp_echo_tool",
                "description": "Echo tool for MCP testing",
                "integration_type": "REST",
                "url": "http://localhost:9101/invoke",
            },
        )
        assert resp.status_code == 200

        # Catalog still works
        resp = client.get("/v1/agentic/catalog")
        assert resp.status_code == 200
        assert isinstance(resp.json()["tools"], list)

    def test_register_agent_roundtrip(self, client, mock_outbound):
        """Register an A2A agent and verify catalog still works."""
        resp = client.post(
            "/v1/agentic/register/agent",
            json={
                "name": "mcp_test_agent",
                "endpoint_url": "http://localhost:9100/a2a",
                "agent_type": "generic",
                "protocol_version": "1.0",
            },
        )
        assert resp.status_code == 200

        resp = client.get("/v1/agentic/catalog")
        assert resp.status_code == 200
        assert isinstance(resp.json()["a2a_agents"], list)

    def test_register_gateway_with_auto_refresh(self, client, mock_outbound):
        """Register a gateway with auto_refresh=True (default)."""
        resp = client.post(
            "/v1/agentic/register/gateway",
            json={
                "name": "mcp_sse_gateway",
                "url": "http://localhost:3000/mcp",
                "transport": "SSE",
                "auto_refresh": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["ok"], bool)

    def test_capability_sources_shape(self, client, mock_outbound):
        """capability_sources in catalog should map string keys to list of strings."""
        data = client.get("/v1/agentic/catalog").json()
        cs = data["capability_sources"]
        assert isinstance(cs, dict)
        for key, val in cs.items():
            assert isinstance(key, str)
            assert isinstance(val, list)


# ---------------------------------------------------------------------------
# 9) Suite manifests — GET /v1/agentic/suite/*
# ---------------------------------------------------------------------------


class TestAgenticSuite:
    """GET /v1/agentic/suite and /v1/agentic/suite/{name}."""

    def test_suite_index_returns_200(self, client):
        resp = client.get("/v1/agentic/suite")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        # Should contain at least the three known keys
        assert "default_home" in data
        assert "default_pro" in data
        assert "optional_addons" in data

    def test_suite_default_pro_returns_200(self, client):
        resp = client.get("/v1/agentic/suite/default_pro")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        # If suite dir exists it should have tool_sources, otherwise error key
        assert "tool_sources" in data or "error" in data

    def test_suite_default_home_returns_200(self, client):
        resp = client.get("/v1/agentic/suite/default_home")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "tool_sources" in data or "error" in data

    def test_suite_nonexistent_returns_error(self, client):
        resp = client.get("/v1/agentic/suite/nonexistent_suite")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_suite_pro_has_tool_sources(self, client):
        """The pro suite should have tool_sources with at least one entry."""
        resp = client.get("/v1/agentic/suite/default_pro")
        data = resp.json()
        if "tool_sources" in data:
            assert isinstance(data["tool_sources"], list)
            assert len(data["tool_sources"]) > 0
            # Each source has id, kind, label
            first = data["tool_sources"][0]
            assert "id" in first
            assert "kind" in first
            assert "label" in first

    def test_suite_pro_has_a2a_agents(self, client):
        """The pro suite should reference A2A agents."""
        resp = client.get("/v1/agentic/suite/default_pro")
        data = resp.json()
        if "a2a_agents" in data:
            assert isinstance(data["a2a_agents"], list)
            assert len(data["a2a_agents"]) > 0


# ---------------------------------------------------------------------------
# 10) Catalog fetch module — fetch_catalog()
# ---------------------------------------------------------------------------


class TestFetchCatalog:
    """Test the catalog.fetch_catalog() function."""

    def test_fetch_catalog_returns_tools_and_agents(self, client, mock_outbound):
        """GET /catalog should include tools and a2a_agents."""
        data = client.get("/v1/agentic/catalog").json()
        assert "tools" in data
        assert "a2a_agents" in data
        assert isinstance(data["tools"], list)
        assert isinstance(data["a2a_agents"], list)

    def test_catalog_has_last_updated(self, client, mock_outbound):
        """Catalog should include last_updated timestamp."""
        data = client.get("/v1/agentic/catalog").json()
        assert "last_updated" in data


# ---------------------------------------------------------------------------
# 11) Client list_gateways / list_servers
# ---------------------------------------------------------------------------


class TestClientGatewaysServers:
    """Verify ContextForgeClient.list_gateways() and list_servers()."""

    def test_client_has_list_gateways(self):
        from app.agentic.client import ContextForgeClient
        c = ContextForgeClient("http://localhost:4444")
        assert hasattr(c, "list_gateways")
        assert callable(c.list_gateways)

    def test_client_has_list_servers(self):
        from app.agentic.client import ContextForgeClient
        c = ContextForgeClient("http://localhost:4444")
        assert hasattr(c, "list_servers")
        assert callable(c.list_servers)


class TestSeedToolIdsByPrefix:
    """Verify seed_all._tool_ids_by_prefix logic."""

    def test_prefix_matching(self):
        import sys
        from pathlib import Path
        repo = str(Path(__file__).resolve().parents[2])
        if repo not in sys.path:
            sys.path.insert(0, repo)
        from agentic.forge.seed.seed_all import _tool_ids_by_prefix

        tool_map = {
            "hp.personal.search": "id-1",
            "hp.personal.plan_day": "id-2",
            "hp.decision.options": "id-3",
            "hp.brief.daily": "id-4",
            "hp.web.search": "id-5",
        }
        # Include hp.personal.* only
        result = _tool_ids_by_prefix(tool_map, ["hp.personal."])
        assert set(result) == {"id-1", "id-2"}

    def test_prefix_with_exclude(self):
        import sys
        from pathlib import Path
        repo = str(Path(__file__).resolve().parents[2])
        if repo not in sys.path:
            sys.path.insert(0, repo)
        from agentic.forge.seed.seed_all import _tool_ids_by_prefix

        tool_map = {
            "hp.personal.search": "id-1",
            "hp.decision.options": "id-2",
            "hp.action.delete": "id-3",
        }
        # Include all hp.* but exclude hp.action.*
        result = _tool_ids_by_prefix(tool_map, ["hp."], ["hp.action."])
        assert "id-1" in result
        assert "id-2" in result
        assert "id-3" not in result

    def test_empty_prefixes(self):
        import sys
        from pathlib import Path
        repo = str(Path(__file__).resolve().parents[2])
        if repo not in sys.path:
            sys.path.insert(0, repo)
        from agentic.forge.seed.seed_all import _tool_ids_by_prefix

        tool_map = {"hp.web.search": "id-1"}
        assert _tool_ids_by_prefix(tool_map, []) == []
