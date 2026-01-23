"""
Civitai API client with caching, rate limiting, and NSFW enforcement.

This module provides enterprise-safe access to Civitai model search:
- API key is OPTIONAL for SFW/public searches
- API key enables NSFW content access
- Results are cached to reduce upstream API pressure
- Responses are normalized to a stable internal schema
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx


class TTLCache:
    """
    Simple in-memory TTL cache.

    Production note: This is process-local. For multi-replica deployments,
    swap to Redis (same interface) and keep the rest unchanged.
    """

    def __init__(self, ttl_seconds: int = 300, max_items: int = 512):
        self.ttl_seconds = int(ttl_seconds)
        self.max_items = int(max_items)
        self._store: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if not item:
            return None
        exp, value = item
        if exp < time.time():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        # Simple eviction if cache is full
        if len(self._store) >= self.max_items:
            oldest_key = min(self._store.items(), key=lambda kv: kv[1][0])[0]
            self._store.pop(oldest_key, None)
        self._store[key] = (time.time() + self.ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()


@dataclass(frozen=True)
class CivitaiSearchQuery:
    """Immutable search query parameters for caching."""
    query: str
    model_type: str = "image"  # "image" or "video"
    limit: int = 20
    page: int = 1
    nsfw: bool = False
    sort: str = "Highest Rated"

    def cache_key(self) -> str:
        """Generate cache key from query parameters."""
        raw = f"q={self.query}|t={self.model_type}|l={self.limit}|p={self.page}|n={int(self.nsfw)}|s={self.sort}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CivitaiClient:
    """
    Civitai API client with:
    - Optional API key support (required for NSFW)
    - Rate limiting (protects against abuse)
    - Response normalization
    """

    BASE_URL = "https://civitai.com/api/v1"
    MIN_REQUEST_INTERVAL = 0.5  # 500ms between requests

    def __init__(self, api_key: Optional[str] = None, timeout_s: float = 15.0):
        self.api_key = api_key
        self.timeout_s = float(timeout_s)
        self._last_request_time = 0.0

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "HomePilot/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _rate_limit(self) -> None:
        """Enforce minimum interval between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    async def search_models(self, q: CivitaiSearchQuery) -> Dict[str, Any]:
        """
        Search Civitai models.

        Args:
            q: Search query parameters

        Returns:
            Raw Civitai API response
        """
        # Map model_type to Civitai types
        # Civitai types: Checkpoint, TextualInversion, Hypernetwork, AestheticGradient,
        #               LORA, Controlnet, Poses, Wildcards, Workflows, VAE, Upscaler,
        #               MotionModule, Other
        if q.model_type == "video":
            types = "MotionModule"  # SVD, AnimateDiff, etc.
        else:
            types = "Checkpoint"  # Image generation models

        params: Dict[str, Any] = {
            "query": q.query,
            "types": types,
            "limit": min(q.limit, 100),  # Civitai max is 100
            "sort": q.sort,
        }
        # NOTE: Civitai API does NOT support 'page' param with query search
        # It requires cursor-based pagination. We omit 'page' to avoid 400 errors.
        # For now, we only return the first page of results.

        # CRITICAL FIX: NSFW parameter handling
        # - Only send "nsfw=true" when NSFW is explicitly requested AND we have an API key
        # - Do NOT send "nsfw=false" - this causes a 400 error from Civitai API
        # - Omitting the nsfw parameter gives us SFW results (default behavior)
        nsfw_mode = "omitted"
        if q.nsfw:
            if self.api_key:
                params["nsfw"] = "true"
                nsfw_mode = "true (authenticated)"
            else:
                # No API key - can't access NSFW, just omit the param for SFW results
                print("[CIVITAI] WARNING: NSFW requested but no API key provided, returning SFW results")
                nsfw_mode = "omitted (no API key)"

        self._rate_limit()

        print(f"[CIVITAI] Searching: query='{q.query}', type={types}, nsfw={nsfw_mode}, limit={params['limit']}")

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.get(
                f"{self.BASE_URL}/models",
                params=params,
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()


def normalize_model_item(item: Dict[str, Any], nsfw_allowed: bool = False) -> Optional[Dict[str, Any]]:
    """
    Normalize a Civitai model item into a stable internal schema.

    Returns None if the item should be filtered out (e.g., NSFW when not allowed).
    """
    # Double-check NSFW filtering (defense in depth)
    is_nsfw = bool(item.get("nsfw")) or bool(item.get("nsfwLevel"))
    if is_nsfw and not nsfw_allowed:
        return None

    model_id = item.get("id")
    creator = (item.get("creator") or {}).get("username", "Unknown")

    stats = item.get("stats") or {}
    download_count = stats.get("downloadCount", 0)
    rating = stats.get("rating", 0)
    rating_count = stats.get("ratingCount", 0)

    # Process versions (limit to 3 most recent)
    versions = item.get("modelVersions") or []
    norm_versions: List[Dict[str, Any]] = []

    for v in versions[:3]:
        files = v.get("files") or []
        primary = next((f for f in files if f.get("primary")), None) or (files[0] if files else None)

        if primary:
            norm_versions.append({
                "id": str(v.get("id")),
                "name": v.get("name", "Unknown"),
                "createdAt": v.get("createdAt"),
                "downloadUrl": (primary or {}).get("downloadUrl") or v.get("downloadUrl"),
                "sizeKB": primary.get("sizeKB", 0),
                "trainedWords": v.get("trainedWords") or [],
            })

    # Get thumbnail from first version's first image
    thumbnail = None
    if versions:
        images = versions[0].get("images") or []
        if images:
            # For NSFW images, Civitai may return blurred preview unless authenticated
            thumbnail = images[0].get("url")

    # Get tags (limit to 5)
    tags = [t.get("name", t) if isinstance(t, dict) else str(t) for t in (item.get("tags") or [])[:5]]

    return {
        "id": str(model_id) if model_id is not None else None,
        "name": item.get("name", "Unknown"),
        "type": item.get("type", "Unknown"),
        "creator": creator,
        "downloads": download_count,
        "rating": rating,
        "ratingCount": rating_count,
        "link": f"https://civitai.com/models/{model_id}" if model_id is not None else None,
        "thumbnail": thumbnail,
        "nsfw": is_nsfw,
        "description": (item.get("description") or "")[:300],  # Truncate long descriptions
        "tags": tags,
        "versions": norm_versions,
    }


async def search_and_normalize(
    *,
    client: CivitaiClient,
    cache: TTLCache,
    query: CivitaiSearchQuery,
) -> Dict[str, Any]:
    """
    Search Civitai and return normalized results.

    Uses cache to reduce API calls.
    """
    key = query.cache_key()
    cached = cache.get(key)
    if cached:
        print(f"[CIVITAI] Cache hit for query: {query.query[:20]}...")
        return cached

    raw = await client.search_models(query)
    items = raw.get("items") or []

    # Normalize and filter items
    normalized_items = []
    for item in items:
        normalized = normalize_model_item(item, nsfw_allowed=query.nsfw)
        if normalized:
            normalized_items.append(normalized)

    result = {
        "items": normalized_items,
        "metadata": raw.get("metadata") or {
            "currentPage": query.page,
            "pageSize": len(normalized_items),
            "totalItems": len(normalized_items),
            "totalPages": 1,
        },
    }

    cache.set(key, result)
    print(f"[CIVITAI] Cached {len(normalized_items)} results for query: {query.query[:20]}...")

    return result


# Global cache instance (shared across requests)
_civitai_cache = TTLCache(ttl_seconds=300, max_items=512)


def get_civitai_cache() -> TTLCache:
    """Get the global Civitai cache instance."""
    return _civitai_cache
