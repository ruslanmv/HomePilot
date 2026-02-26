"""Agentic health smoke tests — lightweight CI-ready checks.

Verifies that the backend agentic layer (tools, MCP servers, A2A agents,
virtual servers) is wired correctly and responds with the expected shapes.
All outbound calls are mocked via conftest.py — no real Forge needed.

Run:
    pytest tests/test_agentic_health.py -v --tb=short
"""

import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_repo_on_path():
    """Put repo root on sys.path so we can import agentic seed modules."""
    repo = str(Path(__file__).resolve().parents[2])
    if repo not in sys.path:
        sys.path.insert(0, repo)


# ===========================================================================
# 1) Catalog health — the single source of truth for all capabilities
# ===========================================================================


class TestCatalogHealth:
    """GET /v1/agentic/catalog returns a well-formed catalog."""

    def test_catalog_returns_200(self, client, mock_outbound):
        r = client.get("/v1/agentic/catalog")
        assert r.status_code == 200

    def test_catalog_has_required_keys(self, client, mock_outbound):
        data = client.get("/v1/agentic/catalog").json()
        for key in ("tools", "a2a_agents", "servers", "gateways", "source"):
            assert key in data, f"catalog missing '{key}'"

    def test_catalog_tools_is_list(self, client, mock_outbound):
        data = client.get("/v1/agentic/catalog").json()
        assert isinstance(data["tools"], list)

    def test_catalog_a2a_agents_is_list(self, client, mock_outbound):
        data = client.get("/v1/agentic/catalog").json()
        assert isinstance(data["a2a_agents"], list)

    def test_catalog_servers_is_list(self, client, mock_outbound):
        data = client.get("/v1/agentic/catalog").json()
        assert isinstance(data["servers"], list)

    def test_catalog_gateways_is_list(self, client, mock_outbound):
        data = client.get("/v1/agentic/catalog").json()
        assert isinstance(data["gateways"], list)

    def test_catalog_has_last_updated(self, client, mock_outbound):
        data = client.get("/v1/agentic/catalog").json()
        assert "last_updated" in data

    def test_catalog_has_forge_status(self, client, mock_outbound):
        data = client.get("/v1/agentic/catalog").json()
        if "forge" in data:
            forge = data["forge"]
            assert "healthy" in forge
            assert isinstance(forge["healthy"], bool)


# ===========================================================================
# 2) Tool shape validation
# ===========================================================================


class TestToolShape:
    """Every tool in the catalog must have id, name, and a status flag."""

    def test_tool_has_required_fields(self, client, mock_outbound):
        tools = client.get("/v1/agentic/catalog").json().get("tools", [])
        for t in tools:
            assert "id" in t, f"tool missing 'id': {t}"
            assert "name" in t, f"tool missing 'name': {t}"
            assert t["id"], "tool id must be non-empty"
            assert t["name"], "tool name must be non-empty"

    def test_tool_enabled_is_boolean_or_null(self, client, mock_outbound):
        tools = client.get("/v1/agentic/catalog").json().get("tools", [])
        for t in tools:
            val = t.get("enabled")
            assert val is None or isinstance(val, bool), (
                f"tool '{t.get('name')}' enabled={val!r} — expected bool or null"
            )


# ===========================================================================
# 3) A2A agent shape validation
# ===========================================================================


class TestA2AAgentShape:
    """Every A2A agent in the catalog must have id, name."""

    def test_a2a_has_required_fields(self, client, mock_outbound):
        agents = client.get("/v1/agentic/catalog").json().get("a2a_agents", [])
        for a in agents:
            assert "id" in a, f"a2a agent missing 'id': {a}"
            assert "name" in a, f"a2a agent missing 'name': {a}"
            assert a["id"], "a2a agent id must be non-empty"
            assert a["name"], "a2a agent name must be non-empty"

    def test_a2a_enabled_is_boolean_or_null(self, client, mock_outbound):
        agents = client.get("/v1/agentic/catalog").json().get("a2a_agents", [])
        for a in agents:
            val = a.get("enabled")
            assert val is None or isinstance(val, bool), (
                f"a2a '{a.get('name')}' enabled={val!r} — expected bool or null"
            )


# ===========================================================================
# 4) Virtual server (MCP server bundle) shape
# ===========================================================================


class TestVirtualServerShape:
    """Virtual servers in the catalog must have id, name, tool_ids."""

    def test_server_has_required_fields(self, client, mock_outbound):
        servers = client.get("/v1/agentic/catalog").json().get("servers", [])
        for s in servers:
            assert "id" in s, f"server missing 'id': {s}"
            assert "name" in s, f"server missing 'name': {s}"

    def test_server_tool_ids_is_list(self, client, mock_outbound):
        servers = client.get("/v1/agentic/catalog").json().get("servers", [])
        for s in servers:
            tids = s.get("tool_ids", s.get("associated_tools", []))
            assert isinstance(tids, list), (
                f"server '{s.get('name')}' tool_ids should be list, got {type(tids)}"
            )


# ===========================================================================
# 5) Gateway shape
# ===========================================================================


class TestGatewayShape:
    """Gateways in the catalog must have id, name."""

    def test_gateway_has_required_fields(self, client, mock_outbound):
        gws = client.get("/v1/agentic/catalog").json().get("gateways", [])
        for g in gws:
            assert "id" in g, f"gateway missing 'id': {g}"
            assert "name" in g, f"gateway missing 'name': {g}"


# ===========================================================================
# 6) Status endpoint health
# ===========================================================================


class TestStatusHealth:
    """GET /v1/agentic/status must always respond."""

    def test_status_200(self, client):
        assert client.get("/v1/agentic/status").status_code == 200

    def test_status_has_enabled_flag(self, client):
        data = client.get("/v1/agentic/status").json()
        assert isinstance(data.get("enabled"), bool)


# ===========================================================================
# 7) Capabilities endpoint health
# ===========================================================================


class TestCapabilitiesHealth:
    """GET /v1/agentic/capabilities returns well-formed data."""

    def test_capabilities_200(self, client):
        assert client.get("/v1/agentic/capabilities").status_code == 200

    def test_capabilities_list(self, client):
        data = client.get("/v1/agentic/capabilities").json()
        assert isinstance(data.get("capabilities"), list)

    def test_builtin_capabilities_present(self, client):
        caps = client.get("/v1/agentic/capabilities").json()["capabilities"]
        ids = {c["id"] for c in caps}
        assert "generate_images" in ids
        assert "generate_videos" in ids


# ===========================================================================
# 8) Sync endpoint health (POST /v1/agentic/sync)
# ===========================================================================


class TestSyncEndpoint:
    """POST /v1/agentic/sync must respond (even if Forge is unreachable)."""

    def test_sync_does_not_500(self, client, mock_outbound):
        """Sync should not crash; 200 or 502 are acceptable in CI."""
        r = client.post("/v1/agentic/sync")
        assert r.status_code in (200, 502)

    def test_sync_returns_summary_on_success(self, client, mock_outbound):
        r = client.post("/v1/agentic/sync")
        if r.status_code == 200:
            data = r.json()
            assert "sync" in data
            summary = data["sync"]
            assert "ok" in summary
            assert "tools_registered" in summary or "tools_skipped" in summary


# ===========================================================================
# 9) Server tools proxy endpoint
# ===========================================================================


class TestServerToolsProxy:
    """GET /v1/agentic/servers/{id}/tools returns a list (or empty)."""

    def test_proxy_returns_list(self, client, mock_outbound):
        r = client.get("/v1/agentic/servers/nonexistent-id/tools")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ===========================================================================
# 10) Sync service — tool prefix matching (unit)
# ===========================================================================


class TestToolPrefixMatching:
    """Unit test for _tool_ids_by_prefix in sync_service."""

    def test_include_matches(self):
        from app.agentic.sync_service import _tool_ids_by_prefix

        tool_map = {
            "hp.web.search": "id-1",
            "hp.web.fetch": "id-2",
            "hp.gmail.search": "id-3",
        }
        result = _tool_ids_by_prefix(tool_map, ["hp.web."])
        assert set(result) == {"id-1", "id-2"}

    def test_exclude_works(self):
        from app.agentic.sync_service import _tool_ids_by_prefix

        tool_map = {
            "hp.web.search": "id-1",
            "hp.action.delete": "id-2",
            "hp.gmail.send": "id-3",
        }
        result = _tool_ids_by_prefix(tool_map, ["hp."], ["hp.action."])
        assert "id-1" in result
        assert "id-3" in result
        assert "id-2" not in result

    def test_empty_map_returns_empty(self):
        from app.agentic.sync_service import _tool_ids_by_prefix

        assert _tool_ids_by_prefix({}, ["hp.web."]) == []

    def test_empty_prefixes_returns_empty(self):
        from app.agentic.sync_service import _tool_ids_by_prefix

        assert _tool_ids_by_prefix({"hp.web.search": "id-1"}, []) == []


# ===========================================================================
# 11) Virtual server templates — all prefixes are well-formed
# ===========================================================================


class TestVirtualServerTemplates:
    """Validate that virtual_servers.yaml prefixes follow hp.* convention."""

    def test_templates_load(self):
        _ensure_repo_on_path()
        from agentic.forge.seed.seed_all import _load_yaml

        data = _load_yaml("virtual_servers.yaml")
        assert "servers" in data
        assert isinstance(data["servers"], list)
        assert len(data["servers"]) > 0

    def test_all_prefixes_start_with_hp(self):
        _ensure_repo_on_path()
        from agentic.forge.seed.seed_all import _load_yaml

        data = _load_yaml("virtual_servers.yaml")
        for spec in data["servers"]:
            name = spec["name"]
            for prefix in spec.get("include_tool_prefixes", []):
                assert prefix.startswith("hp."), (
                    f"vserver '{name}': include prefix '{prefix}' must start with 'hp.'"
                )
            for prefix in spec.get("exclude_tool_prefixes", []):
                assert prefix.startswith("hp."), (
                    f"vserver '{name}': exclude prefix '{prefix}' must start with 'hp.'"
                )

    def test_every_server_has_name(self):
        _ensure_repo_on_path()
        from agentic.forge.seed.seed_all import _load_yaml

        data = _load_yaml("virtual_servers.yaml")
        for spec in data["servers"]:
            assert "name" in spec and spec["name"]


# ===========================================================================
# 12) A2A agent templates — well-formed
# ===========================================================================


class TestA2AAgentTemplates:
    """Validate that a2a_agents.yaml agents have required fields."""

    def test_templates_load(self):
        _ensure_repo_on_path()
        from agentic.forge.seed.seed_all import _load_yaml

        data = _load_yaml("a2a_agents.yaml")
        assert "agents" in data
        assert isinstance(data["agents"], list)

    def test_agents_have_name_and_description(self):
        _ensure_repo_on_path()
        from agentic.forge.seed.seed_all import _load_yaml

        data = _load_yaml("a2a_agents.yaml")
        for agent in data["agents"]:
            assert "name" in agent and agent["name"], (
                f"A2A agent missing 'name': {agent}"
            )
            assert "description" in agent, (
                f"A2A agent '{agent['name']}' missing 'description'"
            )


# ===========================================================================
# 13) Catalog service — type models are importable
# ===========================================================================


class TestCatalogTypes:
    """Verify that catalog Pydantic models are importable and constructable."""

    def test_catalog_tool_model(self):
        from app.agentic.catalog_types import CatalogTool

        t = CatalogTool(id="abc", name="test-tool")
        assert t.id == "abc"
        assert t.name == "test-tool"
        assert t.enabled is None

    def test_catalog_a2a_agent_model(self):
        from app.agentic.catalog_types import CatalogA2AAgent

        a = CatalogA2AAgent(id="xyz", name="test-agent", endpoint_url="http://example.com")
        assert a.id == "xyz"
        assert a.endpoint_url == "http://example.com"

    def test_catalog_server_model(self):
        from app.agentic.catalog_types import CatalogServer

        s = CatalogServer(id="s1", name="test-server", tool_ids=["t1", "t2"])
        assert s.id == "s1"
        assert len(s.tool_ids) == 2

    def test_catalog_gateway_model(self):
        from app.agentic.catalog_types import CatalogGateway

        g = CatalogGateway(id="g1", name="test-gw")
        assert g.id == "g1"

    def test_agentic_catalog_model(self):
        from app.agentic.catalog_types import (
            AgenticCatalog, CatalogTool, CatalogA2AAgent, ForgeStatus,
        )

        cat = AgenticCatalog(
            source="test",
            last_updated="2026-01-01T00:00:00Z",
            forge=ForgeStatus(base_url="http://localhost:4444", healthy=True),
            servers=[],
            tools=[CatalogTool(id="t1", name="tool-1", enabled=True)],
            a2a_agents=[CatalogA2AAgent(id="a1", name="agent-1")],
            gateways=[],
            capability_sources={},
        )
        assert cat.source == "test"
        assert len(cat.tools) == 1
        assert len(cat.a2a_agents) == 1


# ===========================================================================
# 14) Disabled mode — graceful degradation
# ===========================================================================


class TestDisabledMode:
    """When AGENTIC_ENABLED=false, endpoints must not crash."""

    def test_status_still_works(self, client, monkeypatch):
        monkeypatch.setenv("AGENTIC_ENABLED", "false")
        r = client.get("/v1/agentic/status")
        assert r.status_code == 200

    def test_capabilities_still_works(self, client, monkeypatch):
        monkeypatch.setenv("AGENTIC_ENABLED", "false")
        r = client.get("/v1/agentic/capabilities")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data.get("capabilities"), list)
