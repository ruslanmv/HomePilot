"""Normalize raw Matrix Hub responses into MarketplaceItem models."""

from __future__ import annotations

from typing import Any, Dict, List

from .types import MarketplaceItem


def normalize_search_results(raw: Dict[str, Any]) -> List[MarketplaceItem]:
    """Turn raw Matrix Hub search response into a list of MarketplaceItem."""
    items: List[MarketplaceItem] = []
    for entry in raw.get("results", []):
        items.append(
            MarketplaceItem(
                id=entry.get("id", ""),
                name=entry.get("name", entry.get("title", "")),
                description=entry.get("description", ""),
                author=entry.get("author", entry.get("owner", "")),
                install_url=entry.get("manifest_url") or entry.get("install_url"),
                tags=entry.get("tags", []),
                raw=entry,
            )
        )
    return items
