"""
Inventory Core REST API — backend endpoints for project/persona asset queries.

Provides the same functionality as the MCP inventory server but via standard
REST endpoints that the frontend calls directly.

Routes:
  GET /v1/inventory/{project_id}/categories
  GET /v1/inventory/{project_id}/search
  GET /v1/inventory/{project_id}/items/{item_id}
  POST /v1/inventory/resolve
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse

from .auth import require_api_key
from .config import UPLOAD_DIR, PUBLIC_BASE_URL, SQLITE_PATH

router = APIRouter(prefix="/v1/inventory", tags=["inventory"])

# ---------------------------------------------------------------------------
# Helpers (mirrors MCP inventory/app.py — single source of truth is
# projects_metadata.json + file_assets table)
# ---------------------------------------------------------------------------

SENS_ORDER = {"safe": 0, "sensitive": 1, "explicit": 2}
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _sha_id(prefix: str, value: str) -> str:
    h = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{h}"


def _upload_root() -> Path:
    p = Path(UPLOAD_DIR)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[1] / "data" / "uploads"
    return p


def _projects_metadata_path() -> Path:
    return _upload_root() / "projects_metadata.json"


def _load_projects_metadata() -> Dict[str, Any]:
    path = _projects_metadata_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_rel_path(rel_path: str) -> Optional[str]:
    rp = rel_path.replace("\\", "/").lstrip("/")
    if ".." in rp.split("/"):
        return None
    return rp


def _base_url() -> str:
    return (PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")


def _as_file_url(rel_path: str) -> str:
    rp = _safe_rel_path(rel_path)
    if not rp:
        return ""
    return f"{_base_url()}/files/{rp}"


def _allowed_by_sensitivity(item_sens: str, max_sens: str) -> bool:
    return SENS_ORDER.get(item_sens, 0) <= SENS_ORDER.get(max_sens, 0)


def _classify_sensitivity(label: str) -> str:
    low = (label or "").strip().lower()
    if any(k in low for k in ("lingerie", "intimate", "underwear", "bra", "panties", "sexy", "bikini")):
        return "sensitive"
    return "safe"


def _extract_rel_path(url: str) -> str:
    if url.startswith("/files/"):
        return url[len("/files/"):].lstrip("/")
    if url.startswith("files/"):
        return url[len("files/"):].lstrip("/")
    if url.startswith("projects/"):
        return url
    return ""


# ---------------------------------------------------------------------------
# DB access (file_assets table)
# ---------------------------------------------------------------------------

def _open_db() -> Optional[sqlite3.Connection]:
    candidates = [
        Path(SQLITE_PATH),
        _upload_root() / "homepilot.db",
        _upload_root() / "db.sqlite",
        _upload_root().parent / "homepilot.db",
    ]
    for p in candidates:
        if p.exists():
            try:
                conn = sqlite3.connect(str(p))
                conn.row_factory = sqlite3.Row
                return conn
            except Exception:
                continue
    return None


def _db_list_project_files(project_id: str, *, user_id: str = "") -> List[Dict[str, Any]]:
    """List file_assets for a project.

    TODO: When per-user auth is threaded to the inventory router, pass
    user_id here and add ``AND user_id = ?`` to the query so that
    documents from one user never leak into another user's inventory.
    """
    conn = _open_db()
    if not conn:
        return []
    try:
        if user_id:
            cur = conn.execute(
                "SELECT id, kind, rel_path, mime, size_bytes, original_name "
                "FROM file_assets WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            )
        else:
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
# Inventory builder
# ---------------------------------------------------------------------------

def _get_appearance(meta: Dict[str, Any], project_id: str) -> Dict[str, Any]:
    proj = meta.get(project_id) or {}
    return proj.get("persona_appearance") or {}


def _collect_outfit_items(appearance: Dict[str, Any]) -> List[Dict[str, Any]]:
    outfits = appearance.get("outfits") or []
    items: List[Dict[str, Any]] = []
    for o in outfits:
        label = str(o.get("label") or "").strip() or "Outfit"
        item_id = str(o.get("id") or "").strip()
        if not item_id:
            item_id = _sha_id("outfit", f"{label}|{json.dumps(o, sort_keys=True)}")
        sens = str(o.get("sensitivity") or "").strip().lower()
        if sens not in SENS_ORDER:
            sens = _classify_sensitivity(label)

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


def _collect_image_assets(project_id: str, appearance: Dict[str, Any]) -> List[Dict[str, Any]]:
    assets: Dict[str, Dict[str, Any]] = {}

    # Determine the current Active Look (set_id + image_id)
    active_sel = appearance.get("selected") or {}
    active_set_id = str(active_sel.get("set_id") or "").strip()
    active_image_id = str(active_sel.get("image_id") or "").strip()

    def add(asset_id: str, rel_path: str, label: str, tags: List[str], sens: str, *,
            set_id: str = "", image_id: str = "", image_kind: str = "portrait") -> None:
        rp = _safe_rel_path(rel_path)
        if not rp:
            return
        is_active = bool(
            set_id and image_id
            and set_id == active_set_id
            and image_id == active_image_id
        )
        assets[asset_id] = {
            "id": asset_id,
            "type": "image",
            "label": label,
            "tags": list(set(tags)),
            "sensitivity": sens if sens in SENS_ORDER else "safe",
            "rel_path": rp,
            "url": f"/files/{rp}",
            "set_id": set_id,
            "image_id": image_id,
            "is_active_look": is_active,
            "image_kind": image_kind,
        }

    # NOTE: selected_filename / selected_thumb_filename are derived artifacts
    # (committed copies of the Active Look). They are NOT user-facing items
    # and must NOT appear in inventory — they would confuse users with labels
    # like "Avatar (selected)" / "Avatar (thumbnail)".

    for s in appearance.get("sets") or []:
        s_id = str(s.get("set_id") or "").strip()
        for img in s.get("images") or []:
            url = str(img.get("url") or "").strip()
            rel_path = _extract_rel_path(url)
            if not rel_path:
                continue
            img_label = str(img.get("label") or "").strip() or "Portrait"
            img_id = str(img.get("id") or "").strip() or _sha_id("img", f"{project_id}|set|{rel_path}")
            add(img_id, rel_path, img_label, ["portrait", "set"], "safe",
                set_id=s_id, image_id=img_id, image_kind="portrait")

    for o in appearance.get("outfits") or []:
        outfit_label = str(o.get("label") or "").strip() or "Outfit"
        o_set_id = str(o.get("id") or "").strip()
        sens = str(o.get("sensitivity") or "").strip().lower()
        if sens not in SENS_ORDER:
            sens = _classify_sensitivity(outfit_label)
        for img in o.get("images") or []:
            url = str(img.get("url") or "").strip()
            rel_path = _extract_rel_path(url)
            if not rel_path:
                continue
            img_id = (
                str(img.get("id") or "").strip()
                or _sha_id("img", f"{project_id}|outfit|{outfit_label}|{rel_path}")
            )
            add(img_id, rel_path, f"{outfit_label} photo", ["outfit", outfit_label.lower()], sens,
                set_id=o_set_id, image_id=img_id, image_kind="outfit")

    return list(assets.values())


def _collect_document_assets(project_id: str) -> List[Dict[str, Any]]:
    seen_ids: set = set()
    # Track asset_ids (file_assets.id) from project_items so Source 2
    # doesn't re-add the same physical file under a different ID.
    seen_asset_ids: set = set()
    out: List[Dict[str, Any]] = []

    # Source 1: project_items table (preferred — has index_status, tags, etc.)
    try:
        from .project_files import ensure_project_items_table, list_items
        ensure_project_items_table()
        pi_rows = list_items(project_id, category="file")
        for pi in pi_rows:
            item_id = str(pi.get("id") or "").strip()
            if not item_id or item_id in seen_ids:
                continue
            mime = (pi.get("mime") or "").lower()
            if mime.startswith("image/"):
                continue
            seen_ids.add(item_id)
            file_url = pi.get("file_url") or ""
            asset_id = pi.get("asset_id") or ""
            if asset_id:
                seen_asset_ids.add(asset_id)
            props = pi.get("properties") or {}
            if isinstance(props, str):
                try:
                    props = json.loads(props)
                except Exception:
                    props = {}
            tags = pi.get("tags") or []
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = []
            ext = Path(pi.get("original_name") or "").suffix.lstrip(".")
            if ext and ext not in tags:
                tags = [*tags, ext]
            out.append({
                "id": item_id,
                "type": "file",
                "label": pi.get("original_name") or pi.get("name") or "Document",
                "tags": tags,
                "sensitivity": "safe",
                "rel_path": "",
                "mime": mime,
                "size_bytes": int(pi.get("size_bytes") or 0),
                "url": file_url or (f"/files/{asset_id}" if asset_id else ""),
                "index_status": props.get("index_status", ""),
                "chunk_count": props.get("chunk_count", 0),
            })
    except Exception:
        pass

    # Source 2: file_assets table (fallback for docs not in project_items)
    # Skip any file_assets row whose id already appeared as an asset_id in
    # a project_items row — this prevents the same physical file from being
    # counted twice (once as item, once as raw asset).
    rows = _db_list_project_files(project_id)
    for r in rows:
        mime = (r.get("mime") or "").lower()
        if mime.startswith("image/"):
            continue
        rel_path = r.get("rel_path") or ""
        db_id = str(r.get("db_id") or "").strip()
        asset_id = db_id or _sha_id("file", f"{project_id}|{rel_path}")
        if asset_id in seen_ids or asset_id in seen_asset_ids:
            continue
        # Also deduplicate by original_name + size to catch edge cases
        orig_name = r.get("original_name") or Path(rel_path).name
        file_key = f"{orig_name}:{r.get('size_bytes', 0)}"
        if file_key in seen_ids:
            continue
        seen_ids.add(asset_id)
        seen_ids.add(file_key)
        label = orig_name
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


def _build_inventory(project_id: str) -> Dict[str, Any]:
    meta = _load_projects_metadata()
    appearance = _get_appearance(meta, project_id)
    outfits = _collect_outfit_items(appearance)
    images = _collect_image_assets(project_id, appearance)
    files = _collect_document_assets(project_id)

    items_by_id: Dict[str, Dict[str, Any]] = {i["id"]: i for i in outfits}
    assets_by_id: Dict[str, Dict[str, Any]] = {a["id"]: a for a in images}
    for f in files:
        assets_by_id[f["id"]] = f

    for a in list(assets_by_id.values()):
        rp = a.get("rel_path") or ""
        if rp:
            alias = _sha_id("asset", f"{project_id}|{rp}")
            if alias not in assets_by_id:
                assets_by_id[alias] = {**a, "id": alias}

    return {
        "project_id": project_id,
        "outfits": outfits,
        "assets": list({a["id"]: a for a in [*images, *files]}.values()),
        "items_by_id": items_by_id,
        "assets_by_id": assets_by_id,
    }


# ---------------------------------------------------------------------------
# Tag / subcategory helpers
# ---------------------------------------------------------------------------

def _top_tags(items: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    ctr: Counter[str] = Counter()
    for it in items:
        for t in it.get("tags") or []:
            t = str(t).strip().lower()
            if t:
                ctr[t] += 1
    return [{"tag": k, "count": v} for k, v in ctr.most_common(limit)]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/{project_id}/categories", dependencies=[Depends(require_api_key)])
async def inventory_categories(
    project_id: str,
    include_counts: bool = Query(True),
    include_tags: bool = Query(False),
    sensitivity_max: str = Query("safe"),
) -> JSONResponse:
    """List inventory categories with counts and optional tag breakdowns."""
    if not _UUID_RE.match(project_id):
        return JSONResponse(status_code=400, content={"ok": False, "message": "Invalid project_id"})

    if sensitivity_max not in SENS_ORDER:
        sensitivity_max = "safe"

    inv = _build_inventory(project_id)

    outfit_items = [o for o in inv["outfits"]
                    if _allowed_by_sensitivity(o.get("sensitivity", "safe"), sensitivity_max)]
    image_assets = [a for a in inv["assets"] if a.get("type") == "image"
                    and a.get("image_kind") != "outfit"
                    and _allowed_by_sensitivity(a.get("sensitivity", "safe"), sensitivity_max)]
    file_assets = [a for a in inv["assets"] if a.get("type") == "file"
                   and _allowed_by_sensitivity(a.get("sensitivity", "safe"), sensitivity_max)]

    categories = []
    for type_, label, items in [
        ("outfit", "Outfits", outfit_items),
        ("image", "Photos", image_assets),
        ("file", "Documents", file_assets),
    ]:
        cat: Dict[str, Any] = {"type": type_, "label": label}
        if include_counts:
            cat["count"] = len(items)
        if include_tags:
            cat["top_tags"] = _top_tags(items)
        categories.append(cat)

    return JSONResponse(content={
        "ok": True,
        "project_id": project_id,
        "categories": categories,
        "applied_policy": {"sensitivity_max": sensitivity_max, "ts": int(time.time())},
    })


@router.get("/{project_id}/search", dependencies=[Depends(require_api_key)])
async def inventory_search(
    project_id: str,
    query: str = Query(""),
    types: str = Query(""),
    limit: int = Query(30, ge=1, le=100),
    sensitivity_max: str = Query("safe"),
    count_only: bool = Query(False),
) -> JSONResponse:
    """Search inventory items by query text, type, and sensitivity."""
    if not _UUID_RE.match(project_id):
        return JSONResponse(status_code=400, content={"ok": False, "message": "Invalid project_id"})
    if sensitivity_max not in SENS_ORDER:
        sensitivity_max = "safe"

    q = query.strip().lower()
    type_list = [t.strip().lower() for t in types.split(",") if t.strip()] or ["outfit", "image", "file"]

    inv = _build_inventory(project_id)
    results: List[Dict[str, Any]] = []

    def _match(it: Dict[str, Any]) -> bool:
        if not q:
            return True
        label = str(it.get("label") or "").lower()
        desc = str(it.get("description") or "").lower()
        tags = " ".join(str(t).lower() for t in (it.get("tags") or []))
        return q in label or q in desc or q in tags

    if "outfit" in type_list:
        for o in inv["outfits"]:
            if not _allowed_by_sensitivity(o.get("sensitivity", "safe"), sensitivity_max):
                continue
            if not _match(o):
                continue
            # Resolve preview image URL so frontend can display it
            preview_url = ""
            preview_id = o.get("preview_asset_id")
            if preview_id and preview_id in inv["assets_by_id"]:
                preview_asset = inv["assets_by_id"][preview_id]
                preview_url = preview_asset.get("url", "")
            # Resolve set_id + image_id from preview asset for Active Look
            outfit_entry: Dict[str, Any] = {
                "id": o["id"],
                "type": "outfit",
                "label": o.get("label", ""),
                "tags": o.get("tags") or [],
                "sensitivity": o.get("sensitivity", "safe"),
                "preview_asset_id": preview_id,
                "asset_ids": o.get("asset_ids") or [],
                "description": o.get("description", ""),
                "url": preview_url,
            }
            if preview_id and preview_id in inv["assets_by_id"]:
                pa = inv["assets_by_id"][preview_id]
                if pa.get("set_id"):
                    outfit_entry["set_id"] = pa["set_id"]
                if pa.get("image_id"):
                    outfit_entry["image_id"] = pa["image_id"]
                if pa.get("is_active_look"):
                    outfit_entry["is_active_look"] = True
            results.append(outfit_entry)

    for a in inv["assets"]:
        t = a.get("type")
        if t not in type_list:
            continue
        # Outfit photos belong to the outfit item; don't duplicate them as
        # standalone "image" entries (inflates Photos count and All Items).
        if t == "image" and a.get("image_kind") == "outfit":
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
            "url": a.get("url", ""),
        }
        if t == "image":
            # Active Look metadata for wardrobe-style selection
            if a.get("set_id"):
                entry["set_id"] = a["set_id"]
            if a.get("image_id"):
                entry["image_id"] = a["image_id"]
            if a.get("is_active_look"):
                entry["is_active_look"] = True
        if t == "file":
            entry["mime"] = a.get("mime", "")
            entry["size_bytes"] = a.get("size_bytes", 0)
        results.append(entry)

    _order = {"outfit": 0, "image": 1, "file": 2}
    results.sort(key=lambda r: (_order.get(r["type"], 9), str(r.get("label", "")).lower()))

    if count_only:
        return JSONResponse(content={
            "ok": True,
            "project_id": project_id,
            "total_count": len(results),
        })

    return JSONResponse(content={
        "ok": True,
        "project_id": project_id,
        "items": results[:limit],
        "total_count": len(results),
    })


@router.get("/{project_id}/items/{item_id}", dependencies=[Depends(require_api_key)])
async def inventory_get_item(
    project_id: str,
    item_id: str,
    sensitivity_max: str = Query("safe"),
) -> JSONResponse:
    """Get full metadata for a single inventory item or asset."""
    if not _UUID_RE.match(project_id):
        return JSONResponse(status_code=400, content={"ok": False, "message": "Invalid project_id"})
    if sensitivity_max not in SENS_ORDER:
        sensitivity_max = "safe"

    inv = _build_inventory(project_id)

    if item_id in inv["items_by_id"]:
        o = inv["items_by_id"][item_id]
        if not _allowed_by_sensitivity(o.get("sensitivity", "safe"), sensitivity_max):
            return JSONResponse(status_code=403, content={"ok": False, "message": "FORBIDDEN_SENSITIVITY"})
        return JSONResponse(content={"ok": True, "project_id": project_id, "item": o})

    if item_id in inv["assets_by_id"]:
        a = inv["assets_by_id"][item_id]
        if not _allowed_by_sensitivity(a.get("sensitivity", "safe"), sensitivity_max):
            return JSONResponse(status_code=403, content={"ok": False, "message": "FORBIDDEN_SENSITIVITY"})
        out = {k: v for k, v in a.items() if k != "rel_path"}
        return JSONResponse(content={"ok": True, "project_id": project_id, "item": out})

    return JSONResponse(status_code=404, content={"ok": False, "message": "ITEM_NOT_FOUND"})


@router.post("/resolve", dependencies=[Depends(require_api_key)])
async def inventory_resolve(
    body: dict,
) -> JSONResponse:
    """Resolve an asset_id to a safe /files/... URL."""
    project_id = str(body.get("project_id") or "").strip()
    asset_id = str(body.get("asset_id") or body.get("id") or "").strip()

    if not project_id or not _UUID_RE.match(project_id):
        return JSONResponse(status_code=400, content={"ok": False, "message": "Invalid project_id"})
    if not asset_id:
        return JSONResponse(status_code=400, content={"ok": False, "message": "Missing asset_id"})

    sensitivity_max = str(body.get("sensitivity_max") or "safe").strip().lower()
    if sensitivity_max not in SENS_ORDER:
        sensitivity_max = "safe"

    inv = _build_inventory(project_id)
    a = inv["assets_by_id"].get(asset_id)
    if not a:
        return JSONResponse(status_code=404, content={"ok": False, "message": "ITEM_NOT_FOUND"})

    if not _allowed_by_sensitivity(a.get("sensitivity", "safe"), sensitivity_max):
        return JSONResponse(status_code=403, content={"ok": False, "message": "FORBIDDEN_SENSITIVITY"})

    rel_path = a.get("rel_path") or ""
    rp = _safe_rel_path(rel_path)
    if not rp:
        return JSONResponse(status_code=500, content={"ok": False, "message": "RESOLVE_FAILED"})

    return JSONResponse(content={
        "ok": True,
        "project_id": project_id,
        "asset_id": asset_id,
        "type": a.get("type", "image"),
        "label": a.get("label", ""),
        "url": _as_file_url(rp),
        "url_path": f"/files/{rp}",
    })


@router.delete("/{project_id}/items/{item_id}", dependencies=[Depends(require_api_key)])
async def inventory_delete_item(
    project_id: str,
    item_id: str,
) -> JSONResponse:
    """Delete an inventory item (outfit or image) from persona metadata or disk."""
    if not _UUID_RE.match(project_id):
        return JSONResponse(status_code=400, content={"ok": False, "message": "Invalid project_id"})

    meta = _load_projects_metadata()
    proj = meta.get(project_id)
    if not proj:
        return JSONResponse(status_code=404, content={"ok": False, "message": "Project not found"})

    appearance = proj.get("persona_appearance") or {}
    deleted = False
    deleted_label = ""

    # Try deleting from outfits
    outfits = appearance.get("outfits") or []
    new_outfits = []
    for o in outfits:
        oid = str(o.get("id") or "").strip()
        if not oid:
            label = str(o.get("label") or "").strip() or "Outfit"
            oid = _sha_id("outfit", f"{label}|{json.dumps(o, sort_keys=True)}")
        if oid == item_id:
            deleted = True
            deleted_label = str(o.get("label") or "").strip()
            # Also delete associated image files from disk
            for img in o.get("images") or []:
                url = str(img.get("url") or "").strip()
                rel_path = _extract_rel_path(url)
                if rel_path:
                    rp = _safe_rel_path(rel_path)
                    if rp:
                        full_path = _upload_root() / rp
                        if full_path.exists():
                            try:
                                full_path.unlink()
                            except Exception:
                                pass
        else:
            new_outfits.append(o)

    if deleted:
        appearance["outfits"] = new_outfits
        proj["persona_appearance"] = appearance
        meta[project_id] = proj
        try:
            _projects_metadata_path().write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            return JSONResponse(status_code=500, content={
                "ok": False, "message": f"Failed to save metadata: {e}"
            })
        return JSONResponse(content={
            "ok": True,
            "project_id": project_id,
            "deleted_id": item_id,
            "deleted_label": deleted_label,
            "deleted_type": "outfit",
        })

    # ── Check if this is the currently active look (equipped) ──
    active_sel = appearance.get("selected") or {}
    active_set_id = str(active_sel.get("set_id") or "").strip()
    active_image_id = str(active_sel.get("image_id") or "").strip()

    def _is_active_image(img_id: str, set_id: str) -> bool:
        return bool(active_image_id and active_set_id
                     and img_id == active_image_id and set_id == active_set_id)

    # Try deleting an image from sets (portrait photos)
    sets = appearance.get("sets") or []
    for s in sets:
        s_id = str(s.get("set_id") or "").strip()
        images = s.get("images") or []
        new_images = []
        for img in images:
            img_id = str(img.get("id") or "").strip()
            url = str(img.get("url") or "").strip()
            rel_path = _extract_rel_path(url)
            if not img_id:
                img_id = _sha_id("img", f"{project_id}|set|{rel_path}")
            if img_id == item_id:
                if _is_active_image(img_id, s_id):
                    return JSONResponse(status_code=409, content={
                        "ok": False, "message": "Cannot delete the active look. Change the active look first."
                    })
                deleted = True
                deleted_label = str(img.get("label") or "").strip() or "Image"
                if rel_path:
                    rp = _safe_rel_path(rel_path)
                    if rp:
                        full_path = _upload_root() / rp
                        if full_path.exists():
                            try:
                                full_path.unlink()
                            except Exception:
                                pass
            else:
                new_images.append(img)
        s["images"] = new_images

    if deleted:
        # Remove empty sets
        appearance["sets"] = [s for s in sets if s.get("images")]
        proj["persona_appearance"] = appearance
        meta[project_id] = proj
        try:
            _projects_metadata_path().write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            return JSONResponse(status_code=500, content={
                "ok": False, "message": f"Failed to save metadata: {e}"
            })
        return JSONResponse(content={
            "ok": True,
            "project_id": project_id,
            "deleted_id": item_id,
            "deleted_label": deleted_label,
            "deleted_type": "image",
        })

    # Try deleting an individual image from outfit photos
    outfits_for_img = appearance.get("outfits") or []
    for o in outfits_for_img:
        o_id = str(o.get("id") or "").strip()
        images = o.get("images") or []
        new_images = []
        for img in images:
            img_id = str(img.get("id") or "").strip()
            url = str(img.get("url") or "").strip()
            rel_path = _extract_rel_path(url)
            if not img_id:
                outfit_label = str(o.get("label") or "").strip() or "Outfit"
                img_id = _sha_id("img", f"{project_id}|outfit|{outfit_label}|{rel_path}")
            if img_id == item_id:
                if _is_active_image(img_id, o_id):
                    return JSONResponse(status_code=409, content={
                        "ok": False, "message": "Cannot delete the active look. Change the active look first."
                    })
                deleted = True
                deleted_label = str(img.get("label") or "").strip() or str(o.get("label") or "") + " photo"
                if rel_path:
                    rp = _safe_rel_path(rel_path)
                    if rp:
                        full_path = _upload_root() / rp
                        if full_path.exists():
                            try:
                                full_path.unlink()
                            except Exception:
                                pass
            else:
                new_images.append(img)
        o["images"] = new_images

    if deleted:
        appearance["outfits"] = outfits_for_img
        proj["persona_appearance"] = appearance
        meta[project_id] = proj
        try:
            _projects_metadata_path().write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            return JSONResponse(status_code=500, content={
                "ok": False, "message": f"Failed to save metadata: {e}"
            })
        return JSONResponse(content={
            "ok": True,
            "project_id": project_id,
            "deleted_id": item_id,
            "deleted_label": deleted_label,
            "deleted_type": "image",
        })

    # Try deleting from project_items (files / documents)
    if item_id.startswith("item_"):
        try:
            from .project_files import get_item as _pf_get, delete_item as _pf_del
            existing = _pf_get(item_id)
            if existing and existing.get("project_id") == project_id:
                _pf_del(item_id)  # cascades to file_assets + disk
                return JSONResponse(content={
                    "ok": True,
                    "project_id": project_id,
                    "deleted_id": item_id,
                    "deleted_label": existing.get("name") or existing.get("original_name") or "",
                    "deleted_type": existing.get("item_type") or "file",
                })
        except Exception as e:
            return JSONResponse(status_code=500, content={
                "ok": False, "message": f"Failed to delete project item: {e}"
            })

    return JSONResponse(status_code=404, content={"ok": False, "message": "ITEM_NOT_FOUND"})
