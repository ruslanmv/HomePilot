"""MCP server: inventory — read-only query of project/persona assets.

Tools:
  hp.inventory.list_categories  — list Outfits / Photos / Documents with counts
  hp.inventory.search           — search items by query, type, tags
  hp.inventory.get              — get full metadata for one item by id
  hp.inventory.resolve_media    — resolve asset_id to a safe /files/... URL

Storage layout (legacy, authoritative):
  UPLOAD_DIR/
    projects_metadata.json         — all project/persona metadata
    homepilot.db                   — SQLite with file_assets table
    projects/<project_id>/persona/appearance/*  — committed images

The server never exposes absolute disk paths.  All URLs returned use the
/files/<rel_path> convention served by the backend.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Resolve UPLOAD_DIR the same way as backend/app/config.py.
_UPLOAD_DIR_ENV = os.getenv("UPLOAD_DIR", "").strip() or os.getenv("UPLOAD_PATH", "").strip()
if not _UPLOAD_DIR_ENV:
    for _candidate in ("backend/data/uploads", "/app/data/uploads", "data/uploads"):
        if Path(_candidate).exists():
            _UPLOAD_DIR_ENV = _candidate
            break
UPLOAD_ROOT = Path(_UPLOAD_DIR_ENV).resolve() if _UPLOAD_DIR_ENV else Path(".")

PROJECTS_METADATA_PATH = UPLOAD_ROOT / "projects_metadata.json"

# Candidates for the SQLite database (backend uses different names)
_DB_CANDIDATES = [
    UPLOAD_ROOT / "homepilot.db",
    UPLOAD_ROOT / "db.sqlite",
    UPLOAD_ROOT.parent / "homepilot.db",  # DATA_DIR/homepilot.db
]

# Base URL for building /files/... URLs (agents consume these).
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")

# Default sensitivity ceiling.
_DEFAULT_SENS = os.getenv("INVENTORY_DEFAULT_SENSITIVITY_MAX", "safe").strip().lower()
if _DEFAULT_SENS not in ("safe", "sensitive", "explicit"):
    _DEFAULT_SENS = "safe"
DEFAULT_SENSITIVITY_MAX: str = _DEFAULT_SENS

# Optional project allowlist (comma-separated UUIDs).
_ALLOW_RAW = os.getenv("INVENTORY_ALLOW_PROJECT_IDS", "").strip()
ALLOW_PROJECT_IDS = {p.strip() for p in _ALLOW_RAW.split(",") if p.strip()}

# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

SENS_ORDER = {"safe": 0, "sensitive": 1, "explicit": 2}

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_PERSONA_ID_RE = re.compile(r"^persona:[0-9a-fA-F-]{36}$")


def _text(msg: str) -> Json:
    """Return a text-content MCP result."""
    return {"content": [{"type": "text", "text": msg}]}


def _sha_id(prefix: str, value: str) -> str:
    """Deterministic short ID from a prefix and string value."""
    h = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{h}"


def _now_ts() -> int:
    return int(time.time())


def _safe_rel_path(rel_path: str) -> Optional[str]:
    """Sanitise a relative path: no traversal, forward-slash only."""
    rp = rel_path.replace("\\", "/").lstrip("/")
    if ".." in rp.split("/"):
        return None
    return rp


def _as_file_url(rel_path: str) -> str:
    """Turn a safe rel_path into a /files/ URL usable by the frontend."""
    rp = _safe_rel_path(rel_path)
    if not rp:
        return ""
    return f"{BACKEND_BASE_URL}/files/{rp}"


def _allowed_by_sensitivity(item_sens: str, max_sens: str) -> bool:
    return SENS_ORDER.get(item_sens, 0) <= SENS_ORDER.get(max_sens, 0)


def _classify_sensitivity_from_label(label: str) -> str:
    """Heuristic: classify outfit label into a sensitivity bucket."""
    low = (label or "").strip().lower()
    if any(k in low for k in ("lingerie", "intimate", "underwear", "bra", "panties", "sexy", "bikini")):
        return "sensitive"
    return "safe"


# ---------------------------------------------------------------------------
# Scope validation
# ---------------------------------------------------------------------------

class _Scope:
    __slots__ = ("kind", "project_id", "persona_id")

    def __init__(self, kind: str, project_id: str, persona_id: Optional[str] = None):
        self.kind = kind
        self.project_id = project_id
        self.persona_id = persona_id


def _parse_scope(args: Json) -> Tuple[Optional[_Scope], Optional[Json]]:
    """Validate and return a _Scope or an error response."""
    scope = args.get("scope") or {}
    kind = str(scope.get("kind", "")).strip().lower()
    project_id = str(scope.get("project_id", "")).strip()
    persona_id = scope.get("persona_id")
    persona_id = str(persona_id).strip() if persona_id is not None else None

    if kind not in ("persona", "project"):
        return None, _text("Invalid scope.kind — expected 'persona' or 'project'.")
    if not project_id or not _UUID_RE.match(project_id):
        return None, _text("Invalid scope.project_id — expected a UUID.")
    if ALLOW_PROJECT_IDS and project_id not in ALLOW_PROJECT_IDS:
        return None, _text("Access denied: project_id not in allowlist.")
    if kind == "persona" and persona_id and not _PERSONA_ID_RE.match(persona_id):
        return None, _text("Invalid scope.persona_id — expected 'persona:<uuid>'.")

    return _Scope(kind=kind, project_id=project_id, persona_id=persona_id), None


def _get_sensitivity_max(args: Json) -> str:
    s = str(args.get("sensitivity_max") or DEFAULT_SENSITIVITY_MAX).strip().lower()
    return s if s in SENS_ORDER else "safe"


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_projects_metadata() -> Dict[str, Any]:
    if not PROJECTS_METADATA_PATH.exists():
        return {}
    try:
        return json.loads(PROJECTS_METADATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _open_db() -> Optional[sqlite3.Connection]:
    for p in _DB_CANDIDATES:
        if p.exists():
            try:
                conn = sqlite3.connect(str(p))
                conn.row_factory = sqlite3.Row
                return conn
            except Exception:
                continue
    return None


def _db_list_project_files(project_id: str) -> List[Dict[str, Any]]:
    """Query file_assets rows for a project."""
    conn = _open_db()
    if not conn:
        return []
    try:
        cur = conn.execute(
            "SELECT id, kind, rel_path, mime, size_bytes, original_name "
            "FROM file_assets WHERE project_id = ?",
            (project_id,),
        )
        out: List[Dict[str, Any]] = []
        for r in cur.fetchall():
            rp = _safe_rel_path(str(r["rel_path"] or ""))
            if not rp:
                continue
            out.append({
                "db_id": str(r["id"] or ""),
                "kind": str(r["kind"] or ""),
                "rel_path": rp,
                "mime": str(r["mime"] or ""),
                "size_bytes": int(r["size_bytes"] or 0),
                "original_name": str(r["original_name"] or ""),
            })
        return out
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Inventory builder (reads legacy persona_appearance)
# ---------------------------------------------------------------------------

def _get_persona_appearance(meta: Dict[str, Any], project_id: str) -> Dict[str, Any]:
    proj = meta.get(project_id) or {}
    return proj.get("persona_appearance") or {}


def _collect_outfit_items(appearance: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build structured outfit items from persona_appearance.outfits."""
    outfits = appearance.get("outfits") or []
    items: List[Dict[str, Any]] = []
    for o in outfits:
        label = str(o.get("label") or "").strip() or "Outfit"
        item_id = str(o.get("id") or "").strip()
        if not item_id:
            item_id = _sha_id("outfit", f"{label}|{json.dumps(o, sort_keys=True)}")
        sens = str(o.get("sensitivity") or "").strip().lower()
        if sens not in SENS_ORDER:
            sens = _classify_sensitivity_from_label(label)

        imgs = o.get("images") or []
        asset_ids: List[str] = []
        preview_asset_id: Optional[str] = None
        for img in imgs:
            img_id = str(img.get("id") or "").strip()
            url = str(img.get("url") or "").strip()
            rel_path = _extract_rel_path(url)
            if not img_id:
                img_id = _sha_id("img", f"{label}|{rel_path}|{url}")
            if rel_path:
                asset_ids.append(img_id)
                if preview_asset_id is None:
                    preview_asset_id = img_id

        items.append({
            "id": item_id,
            "type": "outfit",
            "label": label,
            "description": str(o.get("outfit_prompt") or o.get("description") or "").strip(),
            "tags": list({*(o.get("tags") or []), label.lower()}),
            "sensitivity": sens,
            "asset_ids": asset_ids,
            "preview_asset_id": preview_asset_id,
        })
    return items


def _extract_rel_path(url: str) -> str:
    """Extract the relative path from a /files/... URL."""
    if url.startswith("/files/"):
        return url[len("/files/"):].lstrip("/")
    if url.startswith("files/"):
        return url[len("files/"):].lstrip("/")
    if url.startswith("projects/"):
        return url
    return ""


def _collect_image_assets(project_id: str, appearance: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build flat image asset list from sets, outfits, and committed avatar."""
    assets: Dict[str, Dict[str, Any]] = {}

    def add(asset_id: str, rel_path: str, label: str, tags: List[str], sens: str) -> None:
        rp = _safe_rel_path(rel_path)
        if not rp:
            return
        assets[asset_id] = {
            "id": asset_id,
            "type": "image",
            "label": label,
            "tags": list(set(tags)),
            "sensitivity": sens if sens in SENS_ORDER else "safe",
            "rel_path": rp,
            "url": f"/files/{rp}",
        }

    # Committed avatar
    sel = str(appearance.get("selected_filename") or "").strip()
    if sel:
        aid = _sha_id("img", f"{project_id}|selected|{sel}")
        add(aid, sel, "Avatar (selected)", ["avatar", "selected"], "safe")

    # Thumbnail
    thumb = str(appearance.get("selected_thumb_filename") or "").strip()
    if thumb:
        aid = _sha_id("img", f"{project_id}|thumb|{thumb}")
        add(aid, thumb, "Avatar (thumbnail)", ["avatar", "thumbnail"], "safe")

    # Portrait sets
    for s in appearance.get("sets") or []:
        for img in s.get("images") or []:
            url = str(img.get("url") or "").strip()
            rel_path = _extract_rel_path(url)
            if not rel_path:
                continue
            img_label = str(img.get("label") or "").strip() or "Portrait"
            img_id = str(img.get("id") or "").strip() or _sha_id("img", f"{project_id}|set|{rel_path}")
            add(img_id, rel_path, img_label, ["portrait", "set"], "safe")

    # Outfit images
    for o in appearance.get("outfits") or []:
        outfit_label = str(o.get("label") or "").strip() or "Outfit"
        sens = str(o.get("sensitivity") or "").strip().lower()
        if sens not in SENS_ORDER:
            sens = _classify_sensitivity_from_label(outfit_label)
        for img in o.get("images") or []:
            url = str(img.get("url") or "").strip()
            rel_path = _extract_rel_path(url)
            if not rel_path:
                continue
            img_id = (
                str(img.get("id") or "").strip()
                or _sha_id("img", f"{project_id}|outfit|{outfit_label}|{rel_path}")
            )
            add(img_id, rel_path, f"{outfit_label} photo", ["outfit", outfit_label.lower()], sens)

    return list(assets.values())


def _collect_document_assets_from_db(project_id: str) -> List[Dict[str, Any]]:
    """Build asset list for non-image files from file_assets table."""
    rows = _db_list_project_files(project_id)
    out: List[Dict[str, Any]] = []
    for r in rows:
        mime = (r.get("mime") or "").lower()
        if mime.startswith("image/"):
            continue  # images handled via persona_appearance
        rel_path = r.get("rel_path") or ""
        label = r.get("original_name") or Path(rel_path).name
        asset_id = str(r.get("db_id") or "").strip() or _sha_id("file", f"{project_id}|{rel_path}")
        ext = Path(rel_path).suffix.lstrip(".")
        out.append({
            "id": asset_id,
            "type": "file",
            "label": label,
            "tags": [r.get("kind", ""), ext] if ext else [r.get("kind", "")],
            "sensitivity": "safe",
            "rel_path": rel_path,
            "mime": mime,
            "size_bytes": int(r.get("size_bytes") or 0),
            "url": f"/files/{rel_path}",
        })
    return out


def _build_inventory(scope: _Scope) -> Dict[str, Any]:
    """Build the full inventory for a project: outfits, images, files."""
    meta = _load_projects_metadata()
    appearance = _get_persona_appearance(meta, scope.project_id)

    outfits = _collect_outfit_items(appearance)
    images = _collect_image_assets(scope.project_id, appearance)
    files = _collect_document_assets_from_db(scope.project_id)

    # Lookup maps
    items_by_id: Dict[str, Dict[str, Any]] = {i["id"]: i for i in outfits}
    assets_by_id: Dict[str, Dict[str, Any]] = {a["id"]: a for a in images}
    for f in files:
        assets_by_id[f["id"]] = f

    # Add rel_path aliases so legacy lookups work
    for a in list(assets_by_id.values()):
        rp = a.get("rel_path") or ""
        if rp:
            alias = _sha_id("asset", f"{scope.project_id}|{rp}")
            if alias not in assets_by_id:
                assets_by_id[alias] = {**a, "id": alias}

    return {
        "project_id": scope.project_id,
        "outfits": outfits,
        "assets": list({a["id"]: a for a in [*images, *files]}.values()),
        "items_by_id": items_by_id,
        "assets_by_id": assets_by_id,
    }


# ---------------------------------------------------------------------------
# Subcategory / tag helpers
# ---------------------------------------------------------------------------

def _top_tags(items: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    ctr: Counter[str] = Counter()
    for it in items:
        for t in it.get("tags") or []:
            t = str(t).strip().lower()
            if t:
                ctr[t] += 1
    return [{"tag": k, "count": v} for k, v in ctr.most_common(limit)]


def _subcats_outfits(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ctr: Counter[str] = Counter()
    for it in items:
        low = (it.get("label") or "").strip().lower()
        if "formal" in low:
            ctr["formal"] += 1
        elif "casual" in low:
            ctr["casual"] += 1
        elif "lingerie" in low:
            ctr["lingerie"] += 1
        else:
            ctr["other"] += 1
    names = {"formal": "Formal", "casual": "Casual", "lingerie": "Lingerie", "other": "Other"}
    return [{"key": k, "label": names.get(k, k.title()), "count": v} for k, v in ctr.most_common()]


def _subcats_images(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ctr: Counter[str] = Counter()
    for it in items:
        tags = {str(t).lower() for t in (it.get("tags") or [])}
        if "avatar" in tags:
            ctr["avatar"] += 1
        elif "portrait" in tags:
            ctr["portrait"] += 1
        elif "outfit" in tags:
            ctr["outfit"] += 1
        else:
            ctr["other"] += 1
    names = {"avatar": "Avatar", "portrait": "Portrait", "outfit": "Outfit", "other": "Other"}
    return [{"key": k, "label": names.get(k, k.title()), "count": v} for k, v in ctr.most_common()]


def _subcats_files(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ctr: Counter[str] = Counter()
    for it in items:
        mime = (it.get("mime") or "").lower()
        if "pdf" in mime:
            ctr["pdf"] += 1
        elif "word" in mime or "doc" in mime:
            ctr["doc"] += 1
        elif "text" in mime or "markdown" in mime:
            ctr["notes"] += 1
        else:
            ctr["other"] += 1
    names = {"pdf": "PDF", "doc": "Docs", "notes": "Notes", "other": "Other"}
    return [{"key": k, "label": names.get(k, k.title()), "count": v} for k, v in ctr.most_common()]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def tool_list_categories(args: Json) -> Json:
    """List inventory categories (Outfits / Photos / Documents) with optional counts and tags."""
    scope, err = _parse_scope(args)
    if err:
        return err
    assert scope is not None

    sensitivity_max = _get_sensitivity_max(args)
    include_counts = bool(args.get("include_counts", True))
    include_tags = bool(args.get("include_tags", False))

    inv = _build_inventory(scope)

    outfit_items = [o for o in inv["outfits"]
                    if _allowed_by_sensitivity(o.get("sensitivity", "safe"), sensitivity_max)]
    image_assets = [a for a in inv["assets"] if a.get("type") == "image"
                    and _allowed_by_sensitivity(a.get("sensitivity", "safe"), sensitivity_max)]
    file_assets = [a for a in inv["assets"] if a.get("type") == "file"
                   and _allowed_by_sensitivity(a.get("sensitivity", "safe"), sensitivity_max)]

    categories: List[Dict[str, Any]] = []

    def _cat(type_: str, label: str, items: List[Dict[str, Any]],
             subcats_fn: Any, ) -> Dict[str, Any]:
        cat: Dict[str, Any] = {"type": type_, "label": label}
        if include_counts:
            cat["count"] = len(items)
        if include_tags:
            cat["top_tags"] = _top_tags(items)
            cat["subcategories"] = subcats_fn(items)
        return cat

    categories.append(_cat("outfit", "Outfits", outfit_items, _subcats_outfits))
    categories.append(_cat("image", "Photos", image_assets, _subcats_images))
    categories.append(_cat("file", "Documents", file_assets, _subcats_files))

    return {
        "project_id": scope.project_id,
        "categories": categories,
        "applied_policy": {"sensitivity_max": sensitivity_max, "ts": _now_ts()},
    }


async def tool_search(args: Json) -> Json:
    """Search inventory items by query text, type, and sensitivity."""
    scope, err = _parse_scope(args)
    if err:
        return err
    assert scope is not None

    sensitivity_max = _get_sensitivity_max(args)
    query = str(args.get("query") or "").strip().lower()
    types = args.get("types") or []
    if not isinstance(types, list) or not types:
        types = ["outfit", "image", "file"]
    types = [str(t).strip().lower() for t in types if str(t).strip()]

    limit = max(1, min(int(args.get("limit") or 20), 100))
    return_count_only = bool(args.get("return_count_only", False))

    inv = _build_inventory(scope)
    results: List[Dict[str, Any]] = []

    def _match(it: Dict[str, Any]) -> bool:
        if not query:
            return True
        label = str(it.get("label") or "").lower()
        desc = str(it.get("description") or "").lower()
        tags = " ".join(str(t).lower() for t in (it.get("tags") or []))
        return query in label or query in desc or query in tags

    # Outfits
    if "outfit" in types:
        for o in inv["outfits"]:
            if not _allowed_by_sensitivity(o.get("sensitivity", "safe"), sensitivity_max):
                continue
            if not _match(o):
                continue
            results.append({
                "id": o["id"],
                "type": "outfit",
                "label": o.get("label", ""),
                "tags": o.get("tags") or [],
                "sensitivity": o.get("sensitivity", "safe"),
                "preview_asset_id": o.get("preview_asset_id"),
            })

    # Images and files
    for a in inv["assets"]:
        t = a.get("type")
        if t not in types:
            continue
        if not _allowed_by_sensitivity(a.get("sensitivity", "safe"), sensitivity_max):
            continue
        if not _match(a):
            continue
        entry: Dict[str, Any] = {
            "id": a["id"],
            "type": t,
            "label": a.get("label", ""),
            "tags": a.get("tags") or [],
            "sensitivity": a.get("sensitivity", "safe"),
        }
        if t == "file":
            entry["mime"] = a.get("mime", "")
        results.append(entry)

    # Deterministic sort: outfits first, then images, then files; alphabetical within
    _order = {"outfit": 0, "image": 1, "file": 2}
    results.sort(key=lambda r: (_order.get(r["type"], 9), str(r.get("label", "")).lower()))

    if return_count_only:
        return {
            "project_id": scope.project_id,
            "total_count": len(results),
            "applied_policy": {"sensitivity_max": sensitivity_max, "ts": _now_ts()},
        }

    return {
        "project_id": scope.project_id,
        "items": results[:limit],
        "total_count": len(results),
        "applied_policy": {"sensitivity_max": sensitivity_max, "ts": _now_ts()},
    }


async def tool_get(args: Json) -> Json:
    """Get full metadata for a single inventory item or asset by ID."""
    scope, err = _parse_scope(args)
    if err:
        return err
    assert scope is not None

    sensitivity_max = _get_sensitivity_max(args)
    item_id = str(args.get("id") or "").strip()
    if not item_id:
        return _text("Missing required field: id")

    inv = _build_inventory(scope)

    # Check outfit items first
    if item_id in inv["items_by_id"]:
        o = inv["items_by_id"][item_id]
        if not _allowed_by_sensitivity(o.get("sensitivity", "safe"), sensitivity_max):
            return _text("FORBIDDEN_SENSITIVITY: item is above sensitivity_max.")
        out = {k: v for k, v in o.items()}
        return {
            "project_id": scope.project_id,
            "item": out,
            "applied_policy": {"sensitivity_max": sensitivity_max, "ts": _now_ts()},
        }

    # Then check assets
    if item_id in inv["assets_by_id"]:
        a = inv["assets_by_id"][item_id]
        if not _allowed_by_sensitivity(a.get("sensitivity", "safe"), sensitivity_max):
            return _text("FORBIDDEN_SENSITIVITY: asset is above sensitivity_max.")
        out = {k: v for k, v in a.items() if k != "rel_path"}
        return {
            "project_id": scope.project_id,
            "item": out,
            "applied_policy": {"sensitivity_max": sensitivity_max, "ts": _now_ts()},
        }

    return _text("ITEM_NOT_FOUND: Unknown id.")


async def tool_resolve_media(args: Json) -> Json:
    """Resolve an asset_id to a safe, renderable URL.

    Rejects unknown IDs (prevents hallucinated asset references).
    Enforces sensitivity_max gating.
    """
    scope, err = _parse_scope(args)
    if err:
        return err
    assert scope is not None

    sensitivity_max = _get_sensitivity_max(args)
    asset_id = str(args.get("asset_id") or args.get("id") or "").strip()
    if not asset_id:
        return _text("Missing required field: asset_id")

    inv = _build_inventory(scope)
    a = inv["assets_by_id"].get(asset_id)
    if not a:
        return _text("ITEM_NOT_FOUND: Unknown asset_id.")

    if not _allowed_by_sensitivity(a.get("sensitivity", "safe"), sensitivity_max):
        return _text("FORBIDDEN_SENSITIVITY: asset is above sensitivity_max.")

    rel_path = a.get("rel_path") or ""
    rp = _safe_rel_path(rel_path)
    if not rp:
        return _text("RESOLVE_FAILED: invalid asset path.")

    url = _as_file_url(rp)
    if not url:
        return _text("RESOLVE_FAILED: could not build URL.")

    return {
        "project_id": scope.project_id,
        "asset_id": asset_id,
        "type": a.get("type", "image"),
        "label": a.get("label", ""),
        "mime": a.get("mime", "image/*"),
        "url": url,
        "url_path": f"/files/{rp}",
        "applied_policy": {"sensitivity_max": sensitivity_max, "ts": _now_ts()},
    }


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.inventory.list_categories",
        description=(
            "List inventory categories (Outfits, Photos, Documents) for a project/persona scope. "
            "Returns counts and optional tag breakdowns. Respects sensitivity_max."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["persona", "project"]},
                        "project_id": {"type": "string", "description": "UUID of the project"},
                        "persona_id": {"type": "string", "description": "persona:<uuid> (required when kind=persona)"},
                    },
                    "required": ["kind", "project_id"],
                },
                "include_counts": {"type": "boolean", "default": True},
                "include_tags": {"type": "boolean", "default": False},
                "sensitivity_max": {
                    "type": "string",
                    "enum": ["safe", "sensitive", "explicit"],
                    "default": DEFAULT_SENSITIVITY_MAX,
                },
            },
            "required": ["scope"],
        },
        handler=tool_list_categories,
    ),
    ToolDef(
        name="hp.inventory.search",
        description=(
            "Search inventory items/assets by query text across outfits, images, and files. "
            "Returns server-issued IDs only (never disk paths). Respects sensitivity_max. "
            "Use return_count_only=true for cheap 'how many photos' queries."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["persona", "project"]},
                        "project_id": {"type": "string"},
                        "persona_id": {"type": "string"},
                    },
                    "required": ["kind", "project_id"],
                },
                "query": {
                    "type": "string",
                    "description": "Search text matched against label, tags, description. Empty returns all.",
                },
                "types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["outfit", "image", "file"]},
                    "description": "Filter by item type. Default: all.",
                },
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                "return_count_only": {"type": "boolean", "default": False},
                "sensitivity_max": {
                    "type": "string",
                    "enum": ["safe", "sensitive", "explicit"],
                    "default": DEFAULT_SENSITIVITY_MAX,
                },
            },
            "required": ["scope"],
        },
        handler=tool_search,
    ),
    ToolDef(
        name="hp.inventory.get",
        description=(
            "Get full metadata for a single inventory item or asset by its server-issued ID. "
            "Rejects unknown/hallucinated IDs with ITEM_NOT_FOUND."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["persona", "project"]},
                        "project_id": {"type": "string"},
                        "persona_id": {"type": "string"},
                    },
                    "required": ["kind", "project_id"],
                },
                "id": {"type": "string", "description": "Item/asset ID from inventory.search or list_categories"},
                "sensitivity_max": {
                    "type": "string",
                    "enum": ["safe", "sensitive", "explicit"],
                    "default": DEFAULT_SENSITIVITY_MAX,
                },
            },
            "required": ["scope", "id"],
        },
        handler=tool_get,
    ),
    ToolDef(
        name="hp.inventory.resolve_media",
        description=(
            "Resolve an image/file asset_id into a renderable /files/... URL. "
            "The ONLY safe gateway from asset_id to URL. Rejects unknown IDs and "
            "enforces sensitivity_max. Even if the LLM guesses an ID, it fails safely."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["persona", "project"]},
                        "project_id": {"type": "string"},
                        "persona_id": {"type": "string"},
                    },
                    "required": ["kind", "project_id"],
                },
                "asset_id": {"type": "string", "description": "Asset ID from inventory.search or inventory.get"},
                "sensitivity_max": {
                    "type": "string",
                    "enum": ["safe", "sensitive", "explicit"],
                    "default": DEFAULT_SENSITIVITY_MAX,
                },
            },
            "required": ["scope", "asset_id"],
        },
        handler=tool_resolve_media,
    ),
]


# ---------------------------------------------------------------------------
# MCP app
# ---------------------------------------------------------------------------

app = create_mcp_app(server_name="homepilot-inventory", tools=TOOLS)
