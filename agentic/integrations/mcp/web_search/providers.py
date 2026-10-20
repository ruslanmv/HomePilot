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
    __slots__ = ("title", "url", "snippet", "source", "published")

    def __init__(self, title: str, url: str, snippet: str, source: str, published: str = ""):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source = source
        self.published = published

    def to_dict(self) -> Dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet, "source": self.source,
                "published": self.published}


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

        params: Dict[str, Any] = {"q": q, "format": "json", "safesearch": 1}
        # Map recency to SearXNG time_range (best-effort). 0 or less: no date filter at all —
        # a question that is not about recent events should not lose the best older pages.
        if recency_days and recency_days > 0:
            if recency_days <= 2:
                params["time_range"] = "day"
            elif recency_days <= 10:
                params["time_range"] = "week"
            elif recency_days <= 40:
                params["time_range"] = "month"
            else:
                params["time_range"] = "year"
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
            results.append(SearchResult(title=title, url=link, snippet=snippet, source="searxng",
                                        published=str(item.get("publishedDate") or "")[:32]))

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
            results.append(SearchResult(title=title, url=link, snippet=snippet, source="tavily",
                                        published=str(item.get("published_date") or "")[:32]))

        return results


# ── Factory ──────────────────────────────────────────────────────────────────

def get_provider() -> SearxngProvider | TavilyProvider:
    if config.PROVIDER == "tavily":
        return TavilyProvider()
    return SearxngProvider()
