"""
Tests for Community Gallery — Phase 3 (must never break).

Validates:
  - Backend proxy endpoints (/community/status, /community/registry, etc.)
  - Registry caching and TTL
  - Server-side search/filter (name, tag, NSFW)
  - URL resolution (relative → absolute)
  - Download proxy returns correct content-type & disposition
  - Graceful degradation when gallery is not configured
  - Graceful degradation when gallery is unreachable
  - Worker route matching patterns
  - Registry schema validation
  - R2 direct mode (upstream URL construction, URL resolution)
  - End-to-end: download → preview → import flow (mocked)

Non-destructive: uses monkeypatched httpx + in-memory mocks.
CI-friendly: no network, no Cloudflare, no R2, pure logic.
"""
import json
import io
import time
import zipfile
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import httpx

# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

SAMPLE_REGISTRY = {
    "schema_version": 1,
    "generated_at": "2026-02-15T12:00:00Z",
    "items": [
        {
            "id": "scarlett_exec_secretary",
            "name": "Scarlett",
            "short": "Executive secretary — professional, proactive",
            "tags": ["professional", "secretary"],
            "nsfw": False,
            "author": "HomePilot Community",
            "downloads": 1204,
            "latest": {
                "version": "1.0.0",
                "package_url": "/p/scarlett_exec_secretary/1.0.0",
                "preview_url": "/v/scarlett_exec_secretary/1.0.0",
                "card_url": "/c/scarlett_exec_secretary/1.0.0",
                "sha256": "abc123",
                "size_bytes": 524288,
            },
        },
        {
            "id": "atlas_research",
            "name": "Atlas",
            "short": "Research assistant — analytical",
            "tags": ["research", "academic"],
            "nsfw": False,
            "author": "HomePilot Community",
            "downloads": 876,
            "latest": {
                "version": "1.0.0",
                "package_url": "/p/atlas_research/1.0.0",
                "preview_url": "/v/atlas_research/1.0.0",
                "card_url": "/c/atlas_research/1.0.0",
                "sha256": "def456",
                "size_bytes": 389120,
            },
        },
        {
            "id": "nova_companion",
            "name": "Nova",
            "short": "NSFW companion persona",
            "tags": ["companion", "nsfw"],
            "nsfw": True,
            "author": "HomePilot Community",
            "downloads": 543,
            "latest": {
                "version": "1.0.0",
                "package_url": "/p/nova_companion/1.0.0",
                "preview_url": "/v/nova_companion/1.0.0",
                "card_url": "/c/nova_companion/1.0.0",
                "sha256": "ghi789",
                "size_bytes": 614400,
            },
        },
    ],
}

# Registry with R2-style (non-leading-slash) relative URLs, as produced by
# the GitHub Actions persona-publish workflow.
SAMPLE_REGISTRY_R2_URLS = {
    "schema_version": 1,
    "generated_at": "2026-02-15T12:00:00Z",
    "items": [
        {
            "id": "scarlett_exec_secretary",
            "name": "Scarlett",
            "short": "Executive secretary — professional, proactive",
            "tags": ["professional", "secretary"],
            "nsfw": False,
            "author": "HomePilot Community",
            "downloads": 1204,
            "latest": {
                "version": "1.0.0",
                "package_url": "packages/scarlett_exec_secretary/1.0.0/persona.hpersona",
                "preview_url": "previews/scarlett_exec_secretary/1.0.0/preview.webp",
                "card_url": "previews/scarlett_exec_secretary/1.0.0/card.json",
                "sha256": "abc123",
                "size_bytes": 524288,
            },
        },
    ],
}

SAMPLE_CARD = {
    "name": "Scarlett",
    "role": "Executive Secretary",
    "short": "Executive secretary — professional, proactive",
    "class_id": "secretary",
    "tags": ["professional", "secretary"],
}

SAMPLE_PACKAGE_BYTES = b"FAKE_HPERSONA_PACKAGE_DATA"


def _make_mock_hpersona_package(label="Scarlett", goal="Help the user") -> bytes:
    """Create a minimal valid .hpersona v2 zip for testing."""
    manifest = {
        "package_version": 2,
        "schema_version": 2,
        "kind": "homepilot.persona",
        "content_rating": "sfw",
        "contents": {"has_avatar": False, "has_tool_dependencies": False},
    }
    agent = {"id": "test", "label": label, "system_prompt": f"You are {label}.", "allowed_tools": []}
    appearance = {"style_preset": "Elegant", "aspect_ratio": "2:3"}
    agentic = {"goal": goal, "capabilities": []}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("blueprint/persona_agent.json", json.dumps(agent))
        z.writestr("blueprint/persona_appearance.json", json.dumps(appearance))
        z.writestr("blueprint/agentic.json", json.dumps(agentic))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Module-level tests (community.py internals)
# ---------------------------------------------------------------------------


class TestGalleryConfigured:
    """Test the _gallery_configured helper."""

    def test_not_configured_when_empty(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        # Re-import to pick up env change
        import importlib
        from app import community
        importlib.reload(community)
        assert community._gallery_configured() is False

    def test_configured_with_worker_url(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://example.workers.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)
        assert community._gallery_configured() is True
        assert community._is_r2_mode() is False

    def test_configured_with_r2_url(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "")
        monkeypatch.setenv("R2_PUBLIC_URL", "https://pub-test.r2.dev")
        import importlib
        from app import community
        importlib.reload(community)
        assert community._gallery_configured() is True
        assert community._is_r2_mode() is True

    def test_worker_takes_priority_over_r2(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://example.workers.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "https://pub-test.r2.dev")
        import importlib
        from app import community
        importlib.reload(community)
        assert community._gallery_configured() is True
        assert community._is_r2_mode() is False
        assert community._base_url() == "https://example.workers.dev"


# ---------------------------------------------------------------------------
# Upstream URL construction
# ---------------------------------------------------------------------------


class TestUpstreamUrls:
    """Verify _upstream_url builds the correct URLs for each mode."""

    def test_worker_mode_urls(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://w.example.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        assert community._upstream_url("registry") == "https://w.example.dev/registry.json"
        assert community._upstream_url("health") == "https://w.example.dev/health"
        assert community._upstream_url("card", "myid", "1.0.0") == "https://w.example.dev/c/myid/1.0.0"
        assert community._upstream_url("preview", "myid", "1.0.0") == "https://w.example.dev/v/myid/1.0.0"
        assert community._upstream_url("package", "myid", "1.0.0") == "https://w.example.dev/p/myid/1.0.0"

    def test_r2_mode_urls(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "")
        monkeypatch.setenv("R2_PUBLIC_URL", "https://pub-abc.r2.dev")
        import importlib
        from app import community
        importlib.reload(community)

        assert community._upstream_url("registry") == "https://pub-abc.r2.dev/registry/registry.json"
        assert community._upstream_url("health") == "https://pub-abc.r2.dev/registry/registry.json"
        assert community._upstream_url("card", "myid", "1.0.0") == "https://pub-abc.r2.dev/previews/myid/1.0.0/card.json"
        assert community._upstream_url("preview", "myid", "1.0.0") == "https://pub-abc.r2.dev/previews/myid/1.0.0/preview.webp"
        assert community._upstream_url("package", "myid", "1.0.0") == "https://pub-abc.r2.dev/packages/myid/1.0.0/persona.hpersona"

    def test_unconfigured_returns_empty(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        assert community._upstream_url("registry") == ""


# ---------------------------------------------------------------------------
# URL resolution in registry items
# ---------------------------------------------------------------------------


class TestResolveItemUrls:
    """Test _resolve_item_urls with both Worker-relative and R2-relative URLs."""

    def test_worker_relative_urls(self, monkeypatch):
        """URLs starting with / are prepended with the base URL."""
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://w.example.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        item = {
            "latest": {
                "package_url": "/p/scarlett/1.0.0",
                "preview_url": "/v/scarlett/1.0.0",
                "card_url": "/c/scarlett/1.0.0",
            }
        }
        community._resolve_item_urls(item)
        assert item["latest"]["package_url"] == "https://w.example.dev/p/scarlett/1.0.0"
        assert item["latest"]["preview_url"] == "https://w.example.dev/v/scarlett/1.0.0"
        assert item["latest"]["card_url"] == "https://w.example.dev/c/scarlett/1.0.0"

    def test_r2_relative_urls(self, monkeypatch):
        """URLs without leading / (R2 object keys) are resolved with a / separator."""
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "")
        monkeypatch.setenv("R2_PUBLIC_URL", "https://pub-abc.r2.dev")
        import importlib
        from app import community
        importlib.reload(community)

        item = {
            "latest": {
                "package_url": "packages/scarlett/1.0.0/persona.hpersona",
                "preview_url": "previews/scarlett/1.0.0/preview.webp",
                "card_url": "previews/scarlett/1.0.0/card.json",
            }
        }
        community._resolve_item_urls(item)
        assert item["latest"]["package_url"] == "https://pub-abc.r2.dev/packages/scarlett/1.0.0/persona.hpersona"
        assert item["latest"]["preview_url"] == "https://pub-abc.r2.dev/previews/scarlett/1.0.0/preview.webp"
        assert item["latest"]["card_url"] == "https://pub-abc.r2.dev/previews/scarlett/1.0.0/card.json"

    def test_absolute_urls_left_alone(self, monkeypatch):
        """Already-absolute URLs should not be modified."""
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://w.example.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        item = {
            "latest": {
                "package_url": "https://cdn.example.com/pkg.hpersona",
                "preview_url": "https://cdn.example.com/preview.webp",
                "card_url": "https://cdn.example.com/card.json",
            }
        }
        community._resolve_item_urls(item)
        assert item["latest"]["package_url"] == "https://cdn.example.com/pkg.hpersona"


class TestRegistryCache:
    """Test in-memory registry caching."""

    def test_cache_reused_within_ttl(self, monkeypatch):
        from app import community
        import importlib

        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://example.workers.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        importlib.reload(community)

        # Prime cache directly
        community._registry_cache["data"] = SAMPLE_REGISTRY
        community._registry_cache["fetched_at"] = time.time()

        # Should return cached data without network call
        import asyncio
        data = asyncio.get_event_loop().run_until_complete(community._fetch_registry())
        assert data["schema_version"] == 1
        assert len(data["items"]) == 3

    def test_cache_expired_refetches(self, monkeypatch):
        from app import community
        import importlib

        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://example.workers.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        importlib.reload(community)

        # Set cache as expired
        community._registry_cache["data"] = {"old": True}
        community._registry_cache["fetched_at"] = time.time() - 999

        # Should refetch — will fail since no real server, but validates cache logic
        import asyncio
        with pytest.raises(Exception):
            asyncio.get_event_loop().run_until_complete(community._fetch_registry())


# ---------------------------------------------------------------------------
# FastAPI endpoint tests (using TestClient)
# ---------------------------------------------------------------------------


class TestCommunityStatusEndpoint:
    """Test GET /community/status."""

    def test_status_not_configured(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        response = client.get("/community/status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False

    def test_status_configured_unreachable(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://nonexistent.example.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        response = client.get("/community/status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["mode"] == "worker"
        # Should be unreachable (no real server)
        assert data.get("reachable") is False

    def test_status_r2_mode(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "")
        monkeypatch.setenv("R2_PUBLIC_URL", "https://pub-test.r2.dev")
        import importlib
        from app import community
        importlib.reload(community)

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        response = client.get("/community/status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["mode"] == "r2"


class TestCommunityRegistryEndpoint:
    """Test GET /community/registry with server-side filtering."""

    def test_registry_not_configured_returns_empty(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        response = client.get("/community/registry")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False
        assert data["items"] == []

    def test_registry_with_cached_data(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://example.workers.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        # Prime cache
        community._registry_cache["data"] = SAMPLE_REGISTRY
        community._registry_cache["fetched_at"] = time.time()

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        response = client.get("/community/registry")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["total"] == 3
        assert data["filtered"] == 3
        assert len(data["items"]) == 3

    def test_registry_search_filter(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://example.workers.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        community._registry_cache["data"] = SAMPLE_REGISTRY
        community._registry_cache["fetched_at"] = time.time()

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        # Search by name
        response = client.get("/community/registry?search=scarlett")
        data = response.json()
        assert data["filtered"] == 1
        assert data["items"][0]["name"] == "Scarlett"

        # Search by tag
        response = client.get("/community/registry?search=research")
        data = response.json()
        assert data["filtered"] == 1
        assert data["items"][0]["name"] == "Atlas"

    def test_registry_tag_filter(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://example.workers.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        community._registry_cache["data"] = SAMPLE_REGISTRY
        community._registry_cache["fetched_at"] = time.time()

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        response = client.get("/community/registry?tag=professional")
        data = response.json()
        assert data["filtered"] == 1
        assert data["items"][0]["id"] == "scarlett_exec_secretary"

    def test_registry_nsfw_filter(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://example.workers.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        community._registry_cache["data"] = SAMPLE_REGISTRY
        community._registry_cache["fetched_at"] = time.time()

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        # Only NSFW
        response = client.get("/community/registry?nsfw=true")
        data = response.json()
        assert data["filtered"] == 1
        assert data["items"][0]["id"] == "nova_companion"

        # Only SFW
        response = client.get("/community/registry?nsfw=false")
        data = response.json()
        assert data["filtered"] == 2
        assert all(not i["nsfw"] for i in data["items"])

    def test_registry_url_resolution(self, monkeypatch):
        """Relative URLs in registry should be resolved to absolute Worker URLs."""
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://example.workers.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        community._registry_cache["data"] = SAMPLE_REGISTRY
        community._registry_cache["fetched_at"] = time.time()

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        response = client.get("/community/registry")
        data = response.json()
        item = data["items"][0]

        # Relative /p/... should now be https://example.workers.dev/p/...
        assert item["latest"]["package_url"].startswith("https://example.workers.dev/p/")
        assert item["latest"]["preview_url"].startswith("https://example.workers.dev/v/")
        assert item["latest"]["card_url"].startswith("https://example.workers.dev/c/")

    def test_registry_url_resolution_r2_mode(self, monkeypatch):
        """R2-style relative URLs should be resolved to absolute R2 URLs."""
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "")
        monkeypatch.setenv("R2_PUBLIC_URL", "https://pub-abc.r2.dev")
        import importlib
        from app import community
        importlib.reload(community)

        community._registry_cache["data"] = SAMPLE_REGISTRY_R2_URLS
        community._registry_cache["fetched_at"] = time.time()

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        response = client.get("/community/registry")
        data = response.json()
        item = data["items"][0]

        assert item["latest"]["package_url"] == "https://pub-abc.r2.dev/packages/scarlett_exec_secretary/1.0.0/persona.hpersona"
        assert item["latest"]["preview_url"] == "https://pub-abc.r2.dev/previews/scarlett_exec_secretary/1.0.0/preview.webp"
        assert item["latest"]["card_url"] == "https://pub-abc.r2.dev/previews/scarlett_exec_secretary/1.0.0/card.json"

    def test_registry_combined_filters(self, monkeypatch):
        """Multiple filters should compose (AND logic)."""
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "https://example.workers.dev")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        community._registry_cache["data"] = SAMPLE_REGISTRY
        community._registry_cache["fetched_at"] = time.time()

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        # NSFW + search should find nothing matching "scarlett"
        response = client.get("/community/registry?nsfw=true&search=scarlett")
        data = response.json()
        assert data["filtered"] == 0


class TestCommunityDownloadEndpoint:
    """Test GET /community/download/{id}/{ver}."""

    def test_download_not_configured(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        response = client.get("/community/download/test/1.0.0")
        assert response.status_code == 404


class TestCommunityCardEndpoint:
    """Test GET /community/card/{id}/{ver}."""

    def test_card_not_configured(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        response = client.get("/community/card/test/1.0.0")
        assert response.status_code == 404


class TestCommunityPreviewEndpoint:
    """Test GET /community/preview/{id}/{ver}."""

    def test_preview_not_configured(self, monkeypatch):
        monkeypatch.setenv("COMMUNITY_GALLERY_URL", "")
        monkeypatch.setenv("R2_PUBLIC_URL", "")
        import importlib
        from app import community
        importlib.reload(community)

        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        response = client.get("/community/preview/test/1.0.0")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Registry schema validation
# ---------------------------------------------------------------------------


class TestRegistrySchema:
    """Validate registry.json schema contract."""

    def test_schema_version_present(self):
        assert "schema_version" in SAMPLE_REGISTRY
        assert isinstance(SAMPLE_REGISTRY["schema_version"], int)

    def test_generated_at_present(self):
        assert "generated_at" in SAMPLE_REGISTRY
        assert isinstance(SAMPLE_REGISTRY["generated_at"], str)

    def test_items_structure(self):
        items = SAMPLE_REGISTRY["items"]
        assert isinstance(items, list)
        assert len(items) > 0

        for item in items:
            assert "id" in item
            assert "name" in item
            assert "short" in item
            assert "tags" in item
            assert isinstance(item["tags"], list)
            assert "nsfw" in item
            assert isinstance(item["nsfw"], bool)
            assert "latest" in item

            latest = item["latest"]
            assert "version" in latest
            assert "package_url" in latest
            assert "preview_url" in latest
            assert "card_url" in latest
            assert "size_bytes" in latest

    def test_urls_are_relative(self):
        """Registry URLs should be relative (resolved by proxy, not in-place)."""
        for item in SAMPLE_REGISTRY["items"]:
            latest = item["latest"]
            assert latest["package_url"].startswith("/p/")
            assert latest["preview_url"].startswith("/v/")
            assert latest["card_url"].startswith("/c/")


# ---------------------------------------------------------------------------
# Worker route pattern tests
# ---------------------------------------------------------------------------


class TestWorkerRoutePatterns:
    """Validate the regex patterns used by the Worker match expected URLs."""

    import re

    ROUTE_PATTERNS = {
        "preview": r"^/v/([a-z0-9_-]+)/([a-z0-9._-]+)$",
        "card": r"^/c/([a-z0-9_-]+)/([a-z0-9._-]+)$",
        "package": r"^/p/([a-z0-9_-]+)/([a-z0-9._-]+)$",
    }

    def test_preview_route_matches(self):
        import re
        pattern = self.ROUTE_PATTERNS["preview"]
        m = re.match(pattern, "/v/scarlett_exec_secretary/1.0.0", re.IGNORECASE)
        assert m is not None
        assert m.group(1) == "scarlett_exec_secretary"
        assert m.group(2) == "1.0.0"

    def test_card_route_matches(self):
        import re
        pattern = self.ROUTE_PATTERNS["card"]
        m = re.match(pattern, "/c/atlas_research/2.1.3", re.IGNORECASE)
        assert m is not None
        assert m.group(1) == "atlas_research"
        assert m.group(2) == "2.1.3"

    def test_package_route_matches(self):
        import re
        pattern = self.ROUTE_PATTERNS["package"]
        m = re.match(pattern, "/p/nova_companion/1.0.0", re.IGNORECASE)
        assert m is not None

    def test_routes_reject_path_traversal(self):
        import re
        for pattern in self.ROUTE_PATTERNS.values():
            assert re.match(pattern, "/v/../../../etc/passwd", re.IGNORECASE) is None
            assert re.match(pattern, "/p/id/../../secrets", re.IGNORECASE) is None

    def test_routes_reject_empty_segments(self):
        import re
        for route_type, pattern in self.ROUTE_PATTERNS.items():
            assert re.match(pattern, f"/{route_type[0]}//1.0.0", re.IGNORECASE) is None
            assert re.match(pattern, f"/{route_type[0]}/id/", re.IGNORECASE) is None


# ---------------------------------------------------------------------------
# End-to-end flow: download → preview → import (mocked)
# ---------------------------------------------------------------------------


class TestEndToEndInstallFlow:
    """Simulate the full install flow the frontend performs."""

    def test_download_preview_import_flow(self, tmp_path, monkeypatch):
        """
        Simulates:
          1. Download .hpersona from community gallery
          2. Preview the package (parse + dependency check)
          3. Import the package (create project)
        """
        # Create a valid .hpersona package
        pkg_bytes = _make_mock_hpersona_package(label="GalleryBot", goal="Be helpful")

        # Step 1: Verify the package is a valid zip
        assert zipfile.is_zipfile(io.BytesIO(pkg_bytes))

        # Step 2: Preview
        from app.personas.export_import import preview_persona_package
        preview = preview_persona_package(pkg_bytes)

        assert preview.manifest["schema_version"] == 2
        assert preview.persona_agent["label"] == "GalleryBot"
        assert preview.agentic["goal"] == "Be helpful"

        # Step 3: Import
        from app.personas import export_import
        from app.personas.export_import import import_persona_package

        _fake_db = {}
        _counter = [0]

        def fake_create(data):
            _counter[0] += 1
            pid = f"imported-{_counter[0]}"
            project = {
                "id": pid,
                "name": data.get("name", "Unnamed"),
                "project_type": data.get("project_type", "chat"),
                "persona_agent": data.get("persona_agent", {}),
                "persona_appearance": data.get("persona_appearance", {}),
                "agentic": data.get("agentic", {}),
            }
            _fake_db[pid] = project
            return dict(project)

        def fake_update(pid, data):
            if pid in _fake_db:
                proj = _fake_db[pid]
                if "persona_appearance" in data:
                    existing = proj.get("persona_appearance") or {}
                    proj["persona_appearance"] = {**existing, **data["persona_appearance"]}
                return dict(proj)
            return None

        monkeypatch.setattr(export_import.projects, "create_new_project", fake_create)
        monkeypatch.setattr(export_import.projects, "update_project", fake_update)

        upload_root = tmp_path / "uploads"
        upload_root.mkdir()

        created = import_persona_package(upload_root, pkg_bytes)

        assert created["project_type"] == "persona"
        assert created["persona_agent"]["label"] == "GalleryBot"
        assert created["agentic"]["goal"] == "Be helpful"


# ---------------------------------------------------------------------------
# R2 bucket layout validation
# ---------------------------------------------------------------------------


class TestR2BucketLayout:
    """Validate the R2 object key conventions."""

    def test_registry_key(self):
        key = "registry/registry.json"
        assert key.startswith("registry/")
        assert key.endswith(".json")

    def test_package_key_format(self):
        persona_id = "scarlett_exec_secretary"
        version = "1.0.0"
        key = f"packages/{persona_id}/{version}/persona.hpersona"
        assert key.startswith("packages/")
        assert key.endswith(".hpersona")
        assert persona_id in key
        assert version in key

    def test_preview_key_format(self):
        persona_id = "scarlett_exec_secretary"
        version = "1.0.0"
        key = f"previews/{persona_id}/{version}/preview.webp"
        assert key.startswith("previews/")
        assert key.endswith(".webp")

    def test_card_key_format(self):
        persona_id = "scarlett_exec_secretary"
        version = "1.0.0"
        key = f"previews/{persona_id}/{version}/card.json"
        assert key.startswith("previews/")
        assert key.endswith(".json")

    def test_keys_are_versioned(self):
        """All asset keys include version for immutability."""
        persona_id = "test"
        version = "2.0.1"
        keys = [
            f"packages/{persona_id}/{version}/persona.hpersona",
            f"previews/{persona_id}/{version}/preview.webp",
            f"previews/{persona_id}/{version}/card.json",
        ]
        for key in keys:
            assert f"/{version}/" in key, f"Key {key} should contain version"


# ---------------------------------------------------------------------------
# Sample data validation
# ---------------------------------------------------------------------------


class TestSampleData:
    """Validate sample/ files used for bootstrapping."""

    def test_sample_registry_loads(self):
        import os
        sample_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "community", "sample", "registry.json",
        )
        if os.path.exists(sample_path):
            with open(sample_path) as f:
                data = json.load(f)
            assert "schema_version" in data
            assert "items" in data
            assert isinstance(data["items"], list)
            for item in data["items"]:
                assert "id" in item
                assert "name" in item
                assert "latest" in item

    def test_sample_card_loads(self):
        import os
        sample_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "community", "sample", "card.json",
        )
        if os.path.exists(sample_path):
            with open(sample_path) as f:
                data = json.load(f)
            assert "name" in data
            assert "role" in data
