"""
Simple unit tests for Civitai API client.

Tests the core search functionality to ensure:
1. SFW searches work without API key (nsfw param omitted)
2. Response normalization works correctly
3. Cache functions work

Note: External API tests may fail due to rate limiting.
"""
import pytest
import httpx


class TestCivitaiApiDirect:
    """Direct tests against Civitai API to verify parameter behavior."""

    @pytest.mark.asyncio
    async def test_search_without_nsfw_param_succeeds(self):
        """
        Test that omitting the nsfw parameter works (expected behavior).
        This is what we should do when nsfw=False.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://civitai.com/api/v1/models",
                params={"query": "realistic", "limit": 3},
            )
            if r.status_code == 503:
                pytest.skip("Civitai API rate limited (503)")
            assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
            data = r.json()
            assert "items" in data
            print(f"SUCCESS: Got {len(data.get('items', []))} results without nsfw param")


class TestCivitaiClient:
    """Tests for the CivitaiClient class."""

    @pytest.mark.asyncio
    async def test_civitai_client_search_sfw(self):
        """Test that CivitaiClient correctly searches for SFW models."""
        from app.civitai import CivitaiClient, CivitaiSearchQuery

        client = CivitaiClient(api_key=None)
        query = CivitaiSearchQuery(
            query="dreamshaper",
            model_type="image",
            limit=3,
            page=1,
            nsfw=False,
        )

        try:
            result = await client.search_models(query)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                pytest.skip("Civitai API rate limited (503)")
            raise

        assert "items" in result, f"Expected 'items' in response: {result}"
        print(f"SUCCESS: CivitaiClient search returned {len(result.get('items', []))} items")

    @pytest.mark.asyncio
    async def test_civitai_search_and_normalize(self):
        """Test full search and normalize flow."""
        from app.civitai import (
            CivitaiClient,
            CivitaiSearchQuery,
            TTLCache,
            search_and_normalize,
        )

        client = CivitaiClient(api_key=None)
        cache = TTLCache(ttl_seconds=60)
        query = CivitaiSearchQuery(
            query="stable diffusion",
            model_type="image",
            limit=3,
            page=1,
            nsfw=False,
        )

        try:
            result = await search_and_normalize(client=client, cache=cache, query=query)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (503, 429):
                pytest.skip(f"Civitai API rate limited ({e.response.status_code})")
            raise

        assert "items" in result
        assert "metadata" in result

        # Check normalized items have expected fields
        for item in result["items"]:
            assert "id" in item
            assert "name" in item
            assert "type" in item
            assert "versions" in item
            print(f"  - {item['name']} ({item['type']})")

        print(f"SUCCESS: Normalized {len(result['items'])} items")


class TestTTLCache:
    """Tests for the TTLCache class."""

    def test_cache_set_and_get(self):
        """Test basic cache operations."""
        from app.civitai import TTLCache

        cache = TTLCache(ttl_seconds=60)
        cache.set("test_key", {"data": "value"})

        result = cache.get("test_key")
        assert result == {"data": "value"}
        print("SUCCESS: Cache set/get works")

    def test_cache_miss(self):
        """Test cache miss returns None."""
        from app.civitai import TTLCache

        cache = TTLCache(ttl_seconds=60)
        result = cache.get("nonexistent")
        assert result is None
        print("SUCCESS: Cache miss returns None")

    def test_cache_clear(self):
        """Test cache clear."""
        from app.civitai import TTLCache

        cache = TTLCache(ttl_seconds=60)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None
        print("SUCCESS: Cache clear works")


class TestCivitaiSearchQuery:
    """Tests for CivitaiSearchQuery dataclass."""

    def test_cache_key_generation(self):
        """Test that cache keys are generated consistently."""
        from app.civitai import CivitaiSearchQuery

        q1 = CivitaiSearchQuery(query="test", nsfw=False)
        q2 = CivitaiSearchQuery(query="test", nsfw=False)
        q3 = CivitaiSearchQuery(query="test", nsfw=True)

        # Same params = same key
        assert q1.cache_key() == q2.cache_key()
        # Different params = different key
        assert q1.cache_key() != q3.cache_key()
        print("SUCCESS: Cache key generation works")


class TestNormalizeModelItem:
    """Tests for model item normalization."""

    def test_normalize_basic_item(self):
        """Test normalizing a basic model item."""
        from app.civitai import normalize_model_item

        item = {
            "id": 123,
            "name": "Test Model",
            "type": "Checkpoint",
            "nsfw": False,
            "creator": {"username": "testuser"},
            "stats": {"downloadCount": 1000, "rating": 4.5, "ratingCount": 50},
            "tags": [{"name": "realistic"}, {"name": "portrait"}],
            "modelVersions": [
                {
                    "id": 456,
                    "name": "v1.0",
                    "files": [{"primary": True, "downloadUrl": "http://example.com/file.safetensors", "sizeKB": 2048}],
                    "images": [{"url": "http://example.com/thumb.jpg"}],
                }
            ],
        }

        result = normalize_model_item(item, nsfw_allowed=False)

        assert result is not None
        assert result["id"] == "123"
        assert result["name"] == "Test Model"
        assert result["type"] == "Checkpoint"
        assert result["creator"] == "testuser"
        assert result["downloads"] == 1000
        assert result["rating"] == 4.5
        assert len(result["versions"]) == 1
        assert result["versions"][0]["id"] == "456"
        print("SUCCESS: Basic item normalization works")

    def test_normalize_filters_nsfw(self):
        """Test that NSFW items are filtered when not allowed."""
        from app.civitai import normalize_model_item

        item = {
            "id": 123,
            "name": "NSFW Model",
            "type": "Checkpoint",
            "nsfw": True,
        }

        result = normalize_model_item(item, nsfw_allowed=False)
        assert result is None, "NSFW item should be filtered"
        print("SUCCESS: NSFW filtering works")

    def test_normalize_allows_nsfw_when_permitted(self):
        """Test that NSFW items are allowed when permitted."""
        from app.civitai import normalize_model_item

        item = {
            "id": 123,
            "name": "NSFW Model",
            "type": "Checkpoint",
            "nsfw": True,
        }

        result = normalize_model_item(item, nsfw_allowed=True)
        assert result is not None, "NSFW item should be allowed"
        assert result["nsfw"] is True
        print("SUCCESS: NSFW items allowed when permitted")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
