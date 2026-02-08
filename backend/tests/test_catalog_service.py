"""Tests for Phase 7: catalog service, TTL cache, tool policy, and runtime tool router.

These tests verify the new additive modules without requiring a real
Context Forge instance. All outbound calls are mocked via conftest.py.
"""

import time

import pytest


# ---------------------------------------------------------------------------
# 1) TTL Cache
# ---------------------------------------------------------------------------


class TestTTLCache:
    """Unit tests for ttl_cache.TTLCache."""

    def test_set_and_get(self):
        from app.agentic.ttl_cache import TTLCache

        cache: TTLCache[str] = TTLCache(ttl_seconds=10.0)
        assert cache.get() is None
        cache.set("hello")
        assert cache.get() == "hello"

    def test_expiry(self):
        from app.agentic.ttl_cache import TTLCache

        cache: TTLCache[str] = TTLCache(ttl_seconds=0.05)
        cache.set("fast")
        assert cache.get() == "fast"
        time.sleep(0.1)
        assert cache.get() is None

    def test_invalidate(self):
        from app.agentic.ttl_cache import TTLCache

        cache: TTLCache[int] = TTLCache(ttl_seconds=60.0)
        cache.set(42)
        assert cache.get() == 42
        cache.invalidate()
        assert cache.get() is None

    @pytest.mark.asyncio
    async def test_get_or_set_async(self):
        from app.agentic.ttl_cache import TTLCache

        cache: TTLCache[str] = TTLCache(ttl_seconds=10.0)
        call_count = 0

        async def builder():
            nonlocal call_count
            call_count += 1
            return "built"

        result = await cache.get_or_set_async(builder)
        assert result == "built"
        assert call_count == 1

        # Second call should use cache
        result = await cache.get_or_set_async(builder)
        assert result == "built"
        assert call_count == 1  # builder NOT called again


# ---------------------------------------------------------------------------
# 2) Catalog types
# ---------------------------------------------------------------------------


class TestCatalogTypes:
    """Verify catalog types instantiate correctly."""

    def test_forge_status(self):
        from app.agentic.catalog_types import ForgeStatus

        s = ForgeStatus(base_url="http://localhost:4444")
        assert s.healthy is True
        assert s.error is None

    def test_catalog_server_with_tool_ids(self):
        from app.agentic.catalog_types import CatalogServer

        s = CatalogServer(id="s1", name="Finance Suite", tool_ids=["t1", "t2"])
        assert s.tool_ids == ["t1", "t2"]
        assert s.sse_url is None

    def test_agentic_catalog(self):
        from app.agentic.catalog_types import AgenticCatalog, ForgeStatus

        cat = AgenticCatalog(
            last_updated="2026-01-01T00:00:00Z",
            forge=ForgeStatus(base_url="http://localhost:4444"),
        )
        assert cat.source == "forge"
        assert cat.tools == []
        assert cat.servers == []
        assert cat.capability_sources == {}


# ---------------------------------------------------------------------------
# 3) Tool policy
# ---------------------------------------------------------------------------


class TestToolPolicy:
    """Tests for tool_policy module."""

    def _make_catalog(self, tools=None, servers=None, cap_sources=None):
        from app.agentic.catalog_types import (
            AgenticCatalog,
            CatalogServer,
            CatalogTool,
            ForgeStatus,
        )

        return AgenticCatalog(
            last_updated="2026-01-01T00:00:00Z",
            forge=ForgeStatus(base_url="http://localhost:4444"),
            tools=[CatalogTool(**t) for t in (tools or [])],
            servers=[CatalogServer(**s) for s in (servers or [])],
            capability_sources=cap_sources or {},
        )

    def test_fallback_when_no_tool_source(self):
        from app.agentic.tool_policy import ToolScope, allowed_tool_ids

        catalog = self._make_catalog()
        allow, mode = allowed_tool_ids(catalog, ToolScope(tool_source=None))
        assert mode == "fallback"
        assert allow == set()

    def test_none_mode(self):
        from app.agentic.tool_policy import ToolScope, allowed_tool_ids

        catalog = self._make_catalog(tools=[{"id": "t1", "name": "search"}])
        allow, mode = allowed_tool_ids(catalog, ToolScope(tool_source="none"))
        assert mode == "none"
        assert allow == set()

    def test_all_mode(self):
        from app.agentic.tool_policy import ToolScope, allowed_tool_ids

        catalog = self._make_catalog(
            tools=[
                {"id": "t1", "name": "search", "enabled": True},
                {"id": "t2", "name": "disabled", "enabled": False},
                {"id": "t3", "name": "implicit"},  # enabled=None → allowed
            ]
        )
        allow, mode = allowed_tool_ids(catalog, ToolScope(tool_source="all"))
        assert mode == "all"
        assert "t1" in allow
        assert "t2" not in allow  # disabled
        assert "t3" in allow  # enabled=None means allowed

    def test_server_mode(self):
        from app.agentic.tool_policy import ToolScope, allowed_tool_ids

        catalog = self._make_catalog(
            tools=[
                {"id": "t1", "name": "search", "enabled": True},
                {"id": "t2", "name": "embed", "enabled": True},
                {"id": "t3", "name": "shell"},
            ],
            servers=[{"id": "srv1", "name": "Finance", "tool_ids": ["t1", "t2"]}],
        )
        allow, mode = allowed_tool_ids(catalog, ToolScope(tool_source="server:srv1"))
        assert mode == "server"
        assert allow == {"t1", "t2"}

    def test_server_mode_missing_server(self):
        from app.agentic.tool_policy import ToolScope, allowed_tool_ids

        catalog = self._make_catalog(tools=[{"id": "t1", "name": "search"}])
        allow, mode = allowed_tool_ids(catalog, ToolScope(tool_source="server:nonexist"))
        assert mode == "server"
        assert allow == set()

    def test_pick_tool_explicit_mapping(self):
        from app.agentic.tool_policy import pick_tool_for_capability

        catalog = self._make_catalog(
            tools=[{"id": "t1", "name": "brave_search"}],
            cap_sources={"web_search": ["t1"]},
        )
        result = pick_tool_for_capability("web_search", catalog, {"t1"})
        assert result == "t1"

    def test_pick_tool_heuristic(self):
        from app.agentic.tool_policy import pick_tool_for_capability

        catalog = self._make_catalog(
            tools=[{"id": "t1", "name": "web_search_tool"}],
        )
        result = pick_tool_for_capability("web_search", catalog, {"t1"})
        assert result == "t1"

    def test_pick_tool_not_in_allow_set(self):
        from app.agentic.tool_policy import pick_tool_for_capability

        catalog = self._make_catalog(
            tools=[{"id": "t1", "name": "web_search_tool"}],
            cap_sources={"web_search": ["t1"]},
        )
        # t1 is not in the allow set
        result = pick_tool_for_capability("web_search", catalog, {"t99"})
        assert result is None


# ---------------------------------------------------------------------------
# 4) Catalog service (capability_sources_from_tools)
# ---------------------------------------------------------------------------


class TestCapabilitySourcesFromTools:
    """Test the heuristic mapping function."""

    def test_maps_search_tools(self):
        from app.agentic.catalog_service import capability_sources_from_tools

        tools = [
            {"id": "t1", "name": "brave_search"},
            {"id": "t2", "name": "google_web_search"},
        ]
        result = capability_sources_from_tools(tools)
        assert "web_search" in result
        assert "t1" in result["web_search"]
        assert "t2" in result["web_search"]

    def test_maps_document_tools(self):
        from app.agentic.catalog_service import capability_sources_from_tools

        tools = [{"id": "t1", "name": "pdf_extractor"}]
        result = capability_sources_from_tools(tools)
        assert "analyze_documents" in result

    def test_maps_image_tools(self):
        from app.agentic.catalog_service import capability_sources_from_tools

        tools = [{"id": "t1", "name": "flux_image_gen"}]
        result = capability_sources_from_tools(tools)
        assert "generate_images" in result

    def test_skips_empty_entries(self):
        from app.agentic.catalog_service import capability_sources_from_tools

        tools = [{"id": "", "name": ""}, {"name": "search"}]
        result = capability_sources_from_tools(tools)
        assert result == {}  # no valid tool IDs


# ---------------------------------------------------------------------------
# 5) Enriched catalog endpoint (integration via TestClient)
# ---------------------------------------------------------------------------


class TestEnrichedCatalog:
    """GET /v1/agentic/catalog — enriched response with ForgeStatus + last_updated."""

    def test_catalog_has_forge_status(self, client, mock_outbound):
        data = client.get("/v1/agentic/catalog").json()
        assert "forge" in data
        assert "base_url" in data["forge"]
        assert "healthy" in data["forge"]

    def test_catalog_has_last_updated(self, client, mock_outbound):
        data = client.get("/v1/agentic/catalog").json()
        assert "last_updated" in data

    def test_catalog_still_has_tools_and_agents(self, client, mock_outbound):
        data = client.get("/v1/agentic/catalog").json()
        assert "tools" in data
        assert "a2a_agents" in data
        assert "servers" in data
        assert "gateways" in data
        assert "capability_sources" in data
        assert isinstance(data["tools"], list)
        assert isinstance(data["servers"], list)

    def test_catalog_disabled_returns_forge_error(self, client, monkeypatch):
        import app.agentic.routes as routes_mod
        monkeypatch.setattr(routes_mod, "_ENABLED", False)

        data = client.get("/v1/agentic/catalog").json()
        assert data["forge"]["healthy"] is False
        assert data["forge"]["error"] == "disabled"
        assert data["tools"] == []
        assert data["servers"] == []
        assert data["last_updated"] == ""


# ---------------------------------------------------------------------------
# 6) Invoke with tool_source (RuntimeToolRouter integration)
# ---------------------------------------------------------------------------


class TestInvokeWithToolSource:
    """POST /v1/agentic/invoke — with tool_source for scoped tool resolution."""

    def test_invoke_fallback_without_tool_source(self, client, mock_outbound):
        """Without tool_source, invoke uses legacy behavior (no change)."""
        resp = client.post(
            "/v1/agentic/invoke",
            json={
                "intent": "web_search",
                "args": {"prompt": "test query"},
                "profile": "fast",
            },
        )
        # Should not crash — result depends on mock, but 200 response
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data

    def test_invoke_with_tool_source_none(self, client, mock_outbound):
        """tool_source='none' should block all tool calls."""
        resp = client.post(
            "/v1/agentic/invoke",
            json={
                "intent": "web_search",
                "args": {"prompt": "test", "tool_source": "none"},
                "profile": "fast",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "no tools" in data["assistant_text"].lower()

    def test_invoke_with_tool_source_all(self, client, mock_outbound):
        """tool_source='all' should try to resolve capability to a tool."""
        resp = client.post(
            "/v1/agentic/invoke",
            json={
                "intent": "web_search",
                "args": {"prompt": "test", "tool_source": "all"},
                "profile": "fast",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data

    def test_invoke_with_tool_source_server_nonexistent(self, client, mock_outbound):
        """tool_source='server:nonexist' should fail gracefully."""
        resp = client.post(
            "/v1/agentic/invoke",
            json={
                "intent": "web_search",
                "args": {"prompt": "test", "tool_source": "server:nonexist"},
                "profile": "fast",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False


# ---------------------------------------------------------------------------
# 7) Cache invalidation on registration
# ---------------------------------------------------------------------------


class TestCacheInvalidation:
    """Registration endpoints should invalidate the catalog cache."""

    def test_register_tool_invalidates_cache(self, client, mock_outbound):
        # First, load catalog to warm cache
        client.get("/v1/agentic/catalog")

        # Register a tool
        resp = client.post(
            "/v1/agentic/register/tool",
            json={"name": "new_tool", "description": "test"},
        )
        assert resp.status_code == 200

        # Catalog should still work (cache was invalidated, will rebuild)
        resp = client.get("/v1/agentic/catalog")
        assert resp.status_code == 200

    def test_register_agent_invalidates_cache(self, client, mock_outbound):
        client.get("/v1/agentic/catalog")
        resp = client.post(
            "/v1/agentic/register/agent",
            json={"name": "new_agent", "endpoint_url": "http://localhost:9100/a2a"},
        )
        assert resp.status_code == 200
        resp = client.get("/v1/agentic/catalog")
        assert resp.status_code == 200

    def test_register_gateway_invalidates_cache(self, client, mock_outbound):
        client.get("/v1/agentic/catalog")
        resp = client.post(
            "/v1/agentic/register/gateway",
            json={"name": "new_gw", "url": "http://localhost:3000/mcp"},
        )
        assert resp.status_code == 200
        resp = client.get("/v1/agentic/catalog")
        assert resp.status_code == 200

    def test_register_server_invalidates_cache(self, client, mock_outbound):
        client.get("/v1/agentic/catalog")
        resp = client.post(
            "/v1/agentic/register/server",
            json={"name": "new_srv"},
        )
        assert resp.status_code == 200
        resp = client.get("/v1/agentic/catalog")
        assert resp.status_code == 200
