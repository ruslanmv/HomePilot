# backend/app/community.py
"""
Community Gallery — backend proxy for the remote persona registry.

Provides a thin caching proxy so the frontend never calls external URLs
directly.  Supports three data sources:

  1. **Worker mode** (production) — a Cloudflare Worker serves clean URLs
     with edge caching and no rate limits (set ``COMMUNITY_GALLERY_URL``).
  2. **R2 direct mode** (fallback) — the R2 bucket has public access enabled
     and the backend reads objects at their raw R2 key paths
     (set ``R2_PUBLIC_URL``).  Rate-limited by Cloudflare — use for
     development only.
  3. **Local samples** (always-on) — bundled personas in
     ``community/sample/`` are always available regardless of network
     connectivity.  They are merged into the registry, and local card /
     preview / package endpoints serve directly from disk.

Priority: ``COMMUNITY_GALLERY_URL`` > ``R2_PUBLIC_URL``.  If neither
variable is configured, the gallery still works with local samples.

Endpoints (mounted on the FastAPI app from main.py):
  GET /community/status              — gallery availability check
  GET /community/registry            — merged remote + local registry
  GET /community/card/{id}/{ver}     — proxy for card.json (local or remote)
  GET /community/preview/{id}/{ver}  — proxy for preview image (local or remote)
  GET /community/download/{id}/{ver} — proxy for .hpersona package (local or remote)
"""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import time
from pathlib import Path
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
# Local samples — bundled personas shipped with HomePilot
# ---------------------------------------------------------------------------

# Resolve path to community/sample/ relative to the project root.
# The backend runs from backend/, so community/ is one level up.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # backend/app/ → backend/ → project root
_SAMPLE_DIR = _PROJECT_ROOT / "community" / "sample"
_SAMPLE_REGISTRY = _SAMPLE_DIR / "registry.json"

# Short-name mapping: registry id → sample directory name
# (e.g. "nora_memory_keeper" → "nora")
_SAMPLE_DIR_MAP: Dict[str, str] = {}

_local_registry_cache: Dict[str, Any] = {"data": None}


def _load_local_registry() -> dict:
    """Load and cache the local sample registry.json."""
    if _local_registry_cache["data"] is not None:
        return _local_registry_cache["data"]

    if not _SAMPLE_REGISTRY.is_file():
        _local_registry_cache["data"] = {"items": [], "schema_version": 1}
        return _local_registry_cache["data"]

    with open(_SAMPLE_REGISTRY, "r") as f:
        data = json.load(f)

    # Build the id → dirname mapping from existing subdirectories
    if _SAMPLE_DIR.is_dir():
        for sub in _SAMPLE_DIR.iterdir():
            if sub.is_dir() and (sub / "manifest.json").exists():
                # The dirname is the short name (e.g. "nora")
                # Match it to registry items whose id starts with the dirname
                for item in data.get("items", []):
                    pid = item.get("id", "")
                    if pid.startswith(sub.name):
                        _SAMPLE_DIR_MAP[pid] = sub.name

    _local_registry_cache["data"] = data
    return data


def _local_sample_path(persona_id: str) -> Optional[Path]:
    """Return the local sample directory for a persona_id, or None."""
    _load_local_registry()  # ensure map is built
    dirname = _SAMPLE_DIR_MAP.get(persona_id)
    if dirname:
        p = _SAMPLE_DIR / dirname
        if p.is_dir():
            return p
    return None


def _local_hpersona_path(persona_id: str) -> Optional[Path]:
    """Return the path to the local .hpersona file, or None."""
    _load_local_registry()
    dirname = _SAMPLE_DIR_MAP.get(persona_id)
    if dirname:
        pkg = _SAMPLE_DIR / f"{dirname}.hpersona"
        if pkg.is_file():
            return pkg
    return None


# ---------------------------------------------------------------------------
# Download counter (SQLite-backed)
# ---------------------------------------------------------------------------


def _get_db_path() -> str:
    from .storage import _get_db_path as _storage_db_path
    return _storage_db_path()


def _ensure_download_table() -> None:
    """Create the community_downloads table if it doesn't exist."""
    con = sqlite3.connect(_get_db_path())
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS community_downloads(
            persona_id TEXT NOT NULL,
            version    TEXT NOT NULL,
            count      INTEGER NOT NULL DEFAULT 0,
            last_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (persona_id, version)
        )
        """
    )
    con.commit()
    con.close()


_download_table_ready = False


def _increment_download(persona_id: str, version: str) -> int:
    """Increment and return the new download count."""
    global _download_table_ready
    if not _download_table_ready:
        _ensure_download_table()
        _download_table_ready = True

    con = sqlite3.connect(_get_db_path())
    con.execute(
        """
        INSERT INTO community_downloads(persona_id, version, count, last_at)
        VALUES (?, ?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(persona_id, version)
        DO UPDATE SET count = count + 1, last_at = CURRENT_TIMESTAMP
        """,
        (persona_id, version),
    )
    con.commit()
    row = con.execute(
        "SELECT count FROM community_downloads WHERE persona_id = ? AND version = ?",
        (persona_id, version),
    ).fetchone()
    con.close()
    return row[0] if row else 0


def _get_all_download_counts() -> Dict[str, int]:
    """Return {persona_id: total_count} for all personas."""
    global _download_table_ready
    if not _download_table_ready:
        _ensure_download_table()
        _download_table_ready = True

    con = sqlite3.connect(_get_db_path())
    rows = con.execute(
        "SELECT persona_id, SUM(count) FROM community_downloads GROUP BY persona_id"
    ).fetchall()
    con.close()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# Mode helpers
# ---------------------------------------------------------------------------


def _gallery_configured() -> bool:
    """True when at least one source is available (remote or local)."""
    return bool(GALLERY_URL) or bool(R2_PUBLIC_URL) or _SAMPLE_REGISTRY.is_file()


def _remote_configured() -> bool:
    """True when a remote upstream (Worker or R2) is configured."""
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


def _resolve_local_urls(item: dict) -> None:
    """Point local-sample URLs to the backend's own /community/* proxy routes.

    The frontend uses ``preview_url`` directly as ``<img src>``, so local
    items must serve through the backend (not the remote Worker).
    """
    pid = item.get("id", "")
    latest = item.get("latest", {})
    ver = latest.get("version", "1.0.0")
    latest["preview_url"] = f"/community/preview/{pid}/{ver}"
    latest["card_url"] = f"/community/card/{pid}/{ver}"
    latest["package_url"] = f"/community/download/{pid}/{ver}"


# ---------------------------------------------------------------------------
# Registry fetch + cache
# ---------------------------------------------------------------------------


async def _fetch_registry() -> dict:
    """Fetch registry from upstream + merge local samples.

    Remote items take precedence over local duplicates (by id).
    Local-only items are marked with ``_source: "local"`` so the
    card/preview/download endpoints know to serve from disk.
    """
    now = time.time()
    if (
        _registry_cache["data"] is not None
        and (now - _registry_cache["fetched_at"]) < _REGISTRY_TTL
    ):
        return _registry_cache["data"]

    remote_data: Optional[dict] = None
    if _remote_configured():
        url = _upstream_url("registry")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                remote_data = resp.json()
        except Exception:
            remote_data = None  # remote unavailable, fall back to local

    # Start with remote items (if available)
    remote_items = remote_data.get("items", []) if remote_data else []
    remote_ids = {item.get("id") for item in remote_items}

    # Load local samples and merge any not already in remote
    local_data = _load_local_registry()
    local_items = local_data.get("items", [])

    merged_items = list(remote_items)
    for item in local_items:
        if item.get("id") not in remote_ids:
            local_item = copy.deepcopy(item)
            local_item["_source"] = "local"
            merged_items.append(local_item)

    data = {
        "schema_version": (remote_data or local_data).get("schema_version", 1),
        "generated_at": (remote_data or local_data).get("generated_at", ""),
        "items": merged_items,
    }

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

    # Determine mode
    if _remote_configured():
        mode = "r2" if _is_r2_mode() else "worker"
        health_url = _upstream_url("health")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(health_url)
                reachable = resp.status_code == 200
        except Exception:
            reachable = False
    else:
        mode = "local"
        reachable = True  # local samples are always reachable

    local_data = _load_local_registry()
    local_count = len(local_data.get("items", []))

    return JSONResponse(
        content={
            "configured": True,
            "url": _base_url() or None,
            "mode": mode,
            "reachable": reachable,
            "local_samples": local_count,
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

    # Resolve URLs: remote items → absolute upstream, local items → backend proxy
    for item in items:
        if item.get("_source") == "local":
            _resolve_local_urls(item)
        else:
            _resolve_item_urls(item)
        item.pop("_source", None)  # strip internal field

    # Merge real download counts from local DB (overrides static registry values)
    try:
        local_counts = _get_all_download_counts()
        for item in items:
            pid = item.get("id", "")
            if pid in local_counts:
                item["downloads"] = local_counts[pid]
    except Exception:
        pass  # Counter read failure must never break registry

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

    # Try local sample first
    sample_dir = _local_sample_path(persona_id)
    if sample_dir:
        card_file = sample_dir / "preview" / "card.json"
        if card_file.is_file():
            return Response(
                content=card_file.read_bytes(),
                media_type="application/json",
                headers={"cache-control": "public, max-age=3600"},
            )

    # Fall back to remote proxy
    if not _remote_configured():
        raise HTTPException(status_code=404, detail="Card not found")

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

    # Try local sample first — look for thumb_avatar_*.webp in assets/
    sample_dir = _local_sample_path(persona_id)
    if sample_dir:
        assets = sample_dir / "assets"
        if assets.is_dir():
            for f in assets.iterdir():
                if f.name.startswith("thumb_avatar_") and f.name.endswith(".webp"):
                    return Response(
                        content=f.read_bytes(),
                        media_type="image/webp",
                        headers={"cache-control": "public, max-age=3600, immutable"},
                    )
            # Fallback: serve any .png avatar if no .webp found
            for f in assets.iterdir():
                if f.name.startswith("avatar_") and f.name.endswith(".png"):
                    return Response(
                        content=f.read_bytes(),
                        media_type="image/png",
                        headers={"cache-control": "public, max-age=3600, immutable"},
                    )

    # Fall back to remote proxy
    if not _remote_configured():
        raise HTTPException(status_code=404, detail="Preview not found")

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

    # Try local sample first
    pkg_path = _local_hpersona_path(persona_id)
    if pkg_path:
        # Track download
        try:
            _increment_download(persona_id, version)
        except Exception:
            pass

        return Response(
            content=pkg_path.read_bytes(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{persona_id}.hpersona"',
                "cache-control": "public, max-age=86400, immutable",
            },
        )

    # Fall back to remote proxy
    if not _remote_configured():
        raise HTTPException(status_code=404, detail="Package not found")

    url = _upstream_url("package", persona_id, version)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to download package: {e}")

    # Track download
    try:
        _increment_download(persona_id, version)
    except Exception:
        pass  # Counter failure must never block the download

    return Response(
        content=resp.content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{persona_id}.hpersona"',
            "cache-control": "public, max-age=86400, immutable",
        },
    )
