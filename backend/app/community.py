# backend/app/community.py
"""
Community Gallery — backend proxy for the remote persona registry.

Provides a thin caching proxy so the frontend never calls external URLs
directly.  Supports two upstream backends:

  1. **Worker mode** (production) — a Cloudflare Worker serves clean URLs
     with edge caching and no rate limits (set ``COMMUNITY_GALLERY_URL``).
  2. **R2 direct mode** (fallback) — the R2 bucket has public access enabled
     and the backend reads objects at their raw R2 key paths
     (set ``R2_PUBLIC_URL``).  Rate-limited by Cloudflare — use for
     development only.

Priority: ``COMMUNITY_GALLERY_URL`` > ``R2_PUBLIC_URL``.  If neither
variable is configured, all endpoints return graceful "gallery not
configured" responses.

Endpoints (mounted on the FastAPI app from main.py):
  GET /community/status              — gallery availability check
  GET /community/registry            — cached proxy for registry.json
  GET /community/card/{id}/{ver}     — proxy for card.json
  GET /community/preview/{id}/{ver}  — proxy for preview image
  GET /community/download/{id}/{ver} — proxy for .hpersona package
"""
from __future__ import annotations

import copy
import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

router = APIRouter(prefix="/community", tags=["community"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Primary — Cloudflare Worker (production, edge-cached, no rate limits)
# Default URL enables gallery out-of-the-box; override via env var or set "" to disable.
_DEFAULT_GALLERY_URL = "https://homepilot-persona-gallery.cloud-data.workers.dev"
GALLERY_URL = os.getenv("COMMUNITY_GALLERY_URL", _DEFAULT_GALLERY_URL).strip().rstrip("/")

# Fallback — R2 direct (development only, rate-limited by Cloudflare)
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "").strip().rstrip("/")

# Simple in-memory cache for the registry (avoids hammering upstream)
_registry_cache: Dict[str, Any] = {"data": None, "fetched_at": 0.0}
_REGISTRY_TTL = 120  # seconds


# ---------------------------------------------------------------------------
# Mode helpers
# ---------------------------------------------------------------------------


def _gallery_configured() -> bool:
    """True when at least one upstream is configured."""
    return bool(GALLERY_URL) or bool(R2_PUBLIC_URL)


def _is_r2_mode() -> bool:
    """True when using R2 direct mode (no Worker)."""
    return not bool(GALLERY_URL) and bool(R2_PUBLIC_URL)


def _base_url() -> str:
    """Return the active upstream base URL."""
    return GALLERY_URL if GALLERY_URL else R2_PUBLIC_URL


def _upstream_url(resource: str, persona_id: str = "", version: str = "") -> str:
    """Build the full upstream URL for a given resource type.

    Worker mode uses short routes (/registry.json, /v/, /c/, /p/).
    R2 direct mode uses raw R2 object keys (registry/, previews/, packages/).
    """
    if not _gallery_configured():
        return ""

    if _is_r2_mode():
        base = R2_PUBLIC_URL
        if resource == "registry":
            return f"{base}/registry/registry.json"
        if resource == "health":
            # No /health in R2 — check if registry is reachable
            return f"{base}/registry/registry.json"
        if resource == "card":
            return f"{base}/previews/{persona_id}/{version}/card.json"
        if resource == "preview":
            return f"{base}/previews/{persona_id}/{version}/preview.webp"
        if resource == "package":
            return f"{base}/packages/{persona_id}/{version}/persona.hpersona"
    else:
        base = GALLERY_URL
        if resource == "registry":
            return f"{base}/registry.json"
        if resource == "health":
            return f"{base}/health"
        if resource == "card":
            return f"{base}/c/{persona_id}/{version}"
        if resource == "preview":
            return f"{base}/v/{persona_id}/{version}"
        if resource == "package":
            return f"{base}/p/{persona_id}/{version}"

    return ""


def _resolve_item_urls(item: dict) -> None:
    """Resolve relative URLs in a registry item to absolute upstream URLs.

    The registry may store URLs in two forms:
      - Worker-relative:  ``/p/id/ver``, ``/v/id/ver``, ``/c/id/ver``
      - R2-relative:      ``packages/id/ver/persona.hpersona``, etc.

    Both are turned into fully-qualified ``https://…`` URLs so the frontend
    can fetch them through the backend proxy or (for debugging) directly.
    """
    latest = item.get("latest", {})
    base = _base_url()
    for key in ("package_url", "preview_url", "card_url"):
        url = latest.get(key, "")
        if url and not url.startswith("http"):
            if url.startswith("/"):
                latest[key] = f"{base}{url}"
            else:
                latest[key] = f"{base}/{url}"


# ---------------------------------------------------------------------------
# Registry fetch + cache
# ---------------------------------------------------------------------------


async def _fetch_registry() -> dict:
    """Fetch registry.json from upstream with caching."""
    now = time.time()
    if (
        _registry_cache["data"] is not None
        and (now - _registry_cache["fetched_at"]) < _REGISTRY_TTL
    ):
        return _registry_cache["data"]

    url = _upstream_url("registry")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    _registry_cache["data"] = data
    _registry_cache["fetched_at"] = now
    return data


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
async def community_status():
    """Check if the community gallery is configured and reachable."""
    if not _gallery_configured():
        return JSONResponse(
            content={
                "configured": False,
                "url": None,
                "mode": None,
                "message": "Community gallery not configured. Set COMMUNITY_GALLERY_URL or R2_PUBLIC_URL in .env.",
            }
        )

    mode = "r2" if _is_r2_mode() else "worker"
    health_url = _upstream_url("health")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(health_url)
            reachable = resp.status_code == 200
    except Exception:
        reachable = False

    return JSONResponse(
        content={
            "configured": True,
            "url": _base_url(),
            "mode": mode,
            "reachable": reachable,
        }
    )


@router.get("/registry")
async def community_registry(
    search: Optional[str] = Query(None, description="Filter personas by name/tags"),
    tag: Optional[str] = Query(None, description="Filter by exact tag"),
    nsfw: Optional[bool] = Query(None, description="Filter by NSFW status"),
):
    """
    Cached proxy for the community persona registry.

    Supports optional server-side filtering for search, tags, and NSFW.
    """
    if not _gallery_configured():
        return JSONResponse(
            content={"items": [], "configured": False},
            status_code=200,
        )

    try:
        data = await _fetch_registry()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch community registry: {e}",
        )

    items = copy.deepcopy(data.get("items", []))

    # Server-side filtering
    if nsfw is not None:
        items = [i for i in items if i.get("nsfw", False) == nsfw]

    if tag:
        tag_lower = tag.lower()
        items = [i for i in items if tag_lower in [t.lower() for t in i.get("tags", [])]]

    if search:
        q = search.lower()
        items = [
            i for i in items
            if q in (i.get("name", "")).lower()
            or q in (i.get("short", "")).lower()
            or q in (i.get("id", "")).lower()
            or any(q in t.lower() for t in i.get("tags", []))
        ]

    # Resolve relative URLs to absolute upstream URLs
    for item in items:
        _resolve_item_urls(item)

    return JSONResponse(
        content={
            "schema_version": data.get("schema_version", 1),
            "generated_at": data.get("generated_at", ""),
            "items": items,
            "total": len(data.get("items", [])),
            "filtered": len(items),
            "configured": True,
        }
    )


@router.get("/card/{persona_id}/{version}")
async def community_card(persona_id: str, version: str):
    """Proxy for a persona card (JSON metadata)."""
    if not _gallery_configured():
        raise HTTPException(status_code=404, detail="Gallery not configured")

    url = _upstream_url("card", persona_id, version)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch card: {e}")

    return Response(
        content=resp.content,
        media_type="application/json",
        headers={"cache-control": "public, max-age=3600"},
    )


@router.get("/preview/{persona_id}/{version}")
async def community_preview(persona_id: str, version: str):
    """Proxy for a persona preview image."""
    if not _gallery_configured():
        raise HTTPException(status_code=404, detail="Gallery not configured")

    url = _upstream_url("preview", persona_id, version)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch preview: {e}")

    return Response(
        content=resp.content,
        media_type="image/webp",
        headers={"cache-control": "public, max-age=3600, immutable"},
    )


@router.get("/download/{persona_id}/{version}")
async def community_download(persona_id: str, version: str):
    """
    Proxy for downloading a .hpersona package.

    The frontend downloads through here, then calls POST /persona/import
    to install it locally.
    """
    if not _gallery_configured():
        raise HTTPException(status_code=404, detail="Gallery not configured")

    url = _upstream_url("package", persona_id, version)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to download package: {e}")

    return Response(
        content=resp.content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{persona_id}.hpersona"',
            "cache-control": "public, max-age=86400, immutable",
        },
    )
