"""Pluggable search providers for the Web Search MCP server.

SearxngProvider — self-hosted SearXNG (home mode, no API keys)
TavilyProvider  — Tavily API (enterprise mode, requires API key)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from . import config


# ── Result type ──────────────────────────────────────────────────────────────

class SearchResult:
    __slots__ = ("title", "url", "snippet", "source")

    def __init__(self, title: str, url: str, snippet: str, source: str):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source = source

    def to_dict(self) -> Dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet, "source": self.source}


# ── SearXNG (home mode) ─────────────────────────────────────────────────────

class SearxngProvider:
    """Query a self-hosted SearXNG instance.  No API keys required."""

    async def search(
        self,
        query: str,
        limit: int = 5,
        recency_days: int = 30,
        domains: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        q = query.strip()
        if domains:
            q += " " + " ".join(f"site:{d}" for d in domains)

        # Map recency to SearXNG time_range (best-effort)
        if recency_days <= 2:
            time_range = "day"
        elif recency_days <= 10:
            time_range = "week"
        elif recency_days <= 40:
            time_range = "month"
        else:
            time_range = "year"

        params = {"q": q, "format": "json", "safesearch": 1, "time_range": time_range}
        url = f"{config.SEARXNG_BASE_URL.rstrip('/')}/search"

        async with httpx.AsyncClient(
            timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
        ) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results: List[SearchResult] = []
        for item in (data.get("results") or [])[:limit]:
            link = (item.get("url") or "").strip()
            if not link:
                continue
            title = (item.get("title") or "Untitled").strip()
            snippet = (item.get("content") or "").strip()
            if len(snippet) > 300:
                snippet = snippet[:300] + "..."
            results.append(SearchResult(title=title, url=link, snippet=snippet, source="searxng"))

        return results


# ── Tavily (enterprise mode) ────────────────────────────────────────────────

class TavilyProvider:
    """Query Tavily search API.  Requires TAVILY_API_KEY."""

    async def search(
        self,
        query: str,
        limit: int = 5,
        recency_days: int = 30,
        domains: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        if not config.TAVILY_API_KEY:
            raise RuntimeError("TAVILY_API_KEY not set but provider=tavily")

        payload: Dict[str, Any] = {
            "api_key": config.TAVILY_API_KEY,
            "query": query,
            "search_depth": "basic",
            "max_results": limit,
        }
        if domains:
            payload["include_domains"] = domains

        async with httpx.AsyncClient(
            timeout=max(config.HTTP_TIMEOUT, 15.0),
            headers={"User-Agent": config.USER_AGENT},
        ) as client:
            resp = await client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
            data = resp.json()

        results: List[SearchResult] = []
        for item in data.get("results") or []:
            link = (item.get("url") or "").strip()
            if not link:
                continue
            title = (item.get("title") or "Untitled").strip()
            snippet = (item.get("content") or "").strip()
            if len(snippet) > 300:
                snippet = snippet[:300] + "..."
            results.append(SearchResult(title=title, url=link, snippet=snippet, source="tavily"))

        return results


# ── Factory ──────────────────────────────────────────────────────────────────

def get_provider() -> SearxngProvider | TavilyProvider:
    if config.PROVIDER == "tavily":
        return TavilyProvider()
    return SearxngProvider()
