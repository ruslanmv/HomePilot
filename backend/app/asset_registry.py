"""
Asset Registry — durable media tracking that survives DB resets.

Core contract:
  1. Every generated image/video gets an `assets` row immediately on creation.
  2. On startup, `reconcile()` scans disk and rebuilds any missing rows.
  3. Landing page APIs fall back to the asset registry when feature tables are empty.

This module is ADDITIVE — it does not modify any existing module.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import UPLOAD_DIR, SQLITE_PATH

# Known filename patterns → feature classification
_FEATURE_PATTERNS = {
    "avatar": "avatar",
    "avatar_instantid": "avatar",
    "avatar_faceswap": "avatar",
    "thumb_avatar": "thumbnail",
    "outfit": "outfit",
    "imagine": "imagine",
    "txt2img": "imagine",
    "img2img": "imagine",
    "ComfyUI": "imagine",
    "animate": "animate",
    "video": "animate",
    "AnimateDiff": "animate",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(SQLITE_PATH)
    con.row_factory = sqlite3.Row
    return con


def _upload_root() -> Path:
    p = Path(UPLOAD_DIR)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[1] / "data" / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_assets_table():
    """Create the assets table if it doesn't exist (idempotent)."""
    con = _db()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL DEFAULT 'image',
            mime TEXT DEFAULT '',
            storage_backend TEXT NOT NULL DEFAULT 'local',
            storage_key TEXT NOT NULL,
            size_bytes INTEGER DEFAULT 0,
            width INTEGER DEFAULT 0,
            height INTEGER DEFAULT 0,
            sha256 TEXT DEFAULT '',
            origin TEXT NOT NULL DEFAULT 'unknown',
            source_hint TEXT DEFAULT '',
            feature TEXT DEFAULT '',
            project_id TEXT DEFAULT '',
            user_id TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(storage_backend, storage_key)
        );
        CREATE INDEX IF NOT EXISTS idx_assets_sha256 ON assets(sha256);
        CREATE INDEX IF NOT EXISTS idx_assets_feature ON assets(feature);
        CREATE INDEX IF NOT EXISTS idx_assets_project ON assets(project_id);
        CREATE INDEX IF NOT EXISTS idx_assets_user ON assets(user_id);
        CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(kind);
    """)
    con.close()


# ── Asset CRUD ─────────────────────────────────────────────────────────────────

def register_asset(
    storage_key: str,
    kind: str = "image",
    mime: str = "",
    size_bytes: int = 0,
    origin: str = "comfy",
    source_hint: str = "",
    feature: str = "",
    project_id: str = "",
    user_id: str = "",
    sha256: str = "",
    width: int = 0,
    height: int = 0,
) -> str:
    """
    Register a new asset. Returns the asset_id.
    If an asset with the same storage_key already exists, returns its ID.
    """
    _ensure_assets_table()
    con = _db()
    cur = con.cursor()

    # Check if already exists
    cur.execute(
        "SELECT id FROM assets WHERE storage_backend = 'local' AND storage_key = ?",
        (storage_key,),
    )
    row = cur.fetchone()
    if row:
        # Update last_seen_at
        cur.execute(
            "UPDATE assets SET last_seen_at = datetime('now') WHERE id = ?",
            (row["id"],),
        )
        con.commit()
        con.close()
        return row["id"]

    asset_id = f"a_{uuid.uuid4().hex[:20]}"
    cur.execute(
        """
        INSERT INTO assets(
            id, kind, mime, storage_backend, storage_key,
            size_bytes, width, height, sha256,
            origin, source_hint, feature, project_id, user_id
        ) VALUES (?,?,?,'local',?,?,?,?,?,?,?,?,?,?)
        """,
        (asset_id, kind, mime or "", storage_key,
         size_bytes, width, height, sha256 or "",
         origin, source_hint or "", feature or "",
         project_id or "", user_id or ""),
    )
    con.commit()
    con.close()
    return asset_id


def get_asset(asset_id: str) -> Optional[Dict[str, Any]]:
    """Look up an asset by ID."""
    _ensure_assets_table()
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM assets WHERE id = ?", (asset_id,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def find_asset_id_by_storage_key(storage_key: str) -> Optional[str]:
    """Reverse-lookup: storage_key → asset_id.

    Used by the persona-library link phase to backfill the
    ``registry_asset_id`` field on older library rows that were
    saved before that field existed. The ``UNIQUE(storage_backend,
    storage_key)`` constraint on the assets table guarantees at
    most one row per storage_key, so this is a safe O(1) lookup.
    """
    if not storage_key:
        return None
    _ensure_assets_table()
    con = _db()
    cur = con.cursor()
    cur.execute(
        "SELECT id FROM assets WHERE storage_backend = 'local' AND storage_key = ?",
        (storage_key,),
    )
    row = cur.fetchone()
    con.close()
    if not row:
        return None
    return str(row["id"])


def list_assets(
    feature: str = "",
    kind: str = "",
    project_id: str = "",
    user_id: str = "",
    limit: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List assets with optional filters."""
    _ensure_assets_table()
    con = _db()
    cur = con.cursor()

    clauses = []
    params: list = []
    if feature:
        clauses.append("feature = ?")
        params.append(feature)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend([limit, offset])

    cur.execute(
        f"SELECT * FROM assets {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params,
    )
    rows = cur.fetchall()
    con.close()
    return [dict(r) for r in rows]


def count_assets(feature: str = "", kind: str = "") -> int:
    """Count assets with optional filters."""
    _ensure_assets_table()
    con = _db()
    cur = con.cursor()
    clauses = []
    params: list = []
    if feature:
        clauses.append("feature = ?")
        params.append(feature)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    cur.execute(f"SELECT COUNT(*) FROM assets {where}", params)
    count = cur.fetchone()[0]
    con.close()
    return count


# ── Feature classification ─────────────────────────────────────────────────────

def classify_filename(filename: str) -> str:
    """Classify a filename into a feature category."""
    name = os.path.basename(filename).lower()
    # Check prefixes in order (longest first to avoid partial matches)
    for prefix in sorted(_FEATURE_PATTERNS.keys(), key=len, reverse=True):
        if name.startswith(prefix.lower()):
            return _FEATURE_PATTERNS[prefix]
    return ""


def classify_path(rel_path: str) -> tuple[str, str]:
    """
    Classify by path structure.
    Returns (feature, project_id).
    """
    parts = Path(rel_path).parts
    feature = classify_filename(rel_path)
    project_id = ""

    # projects/<project_id>/persona/appearance/...
    if "projects" in parts:
        idx = list(parts).index("projects")
        if idx + 1 < len(parts):
            project_id = parts[idx + 1]
        if "persona" in parts and "appearance" in parts:
            if not feature:
                feature = "avatar"

    return feature, project_id


# ── Reconcile (rebuild from disk) ──────────────────────────────────────────────

def reconcile(
    extra_dirs: Optional[List[str]] = None,
    verbose: bool = True,
) -> Dict[str, int]:
    """
    Scan disk and rebuild the assets table from files found.

    Returns stats: {created, updated, skipped, errors}
    """
    _ensure_assets_table()
    root = _upload_root()
    stats = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}

    scan_roots = [str(root)]
    if extra_dirs:
        scan_roots.extend(extra_dirs)

    for scan_root in scan_roots:
        scan_path = Path(scan_root)
        if not scan_path.is_dir():
            continue

        if verbose:
            print(f"[RECONCILE] Scanning: {scan_path}")

        for dirpath, dirnames, filenames in os.walk(str(scan_path)):
            # Skip hidden / irrelevant dirs
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in ("__pycache__", "node_modules")
            ]

            for fname in filenames:
                ext = Path(fname).suffix.lower()
                if ext not in MEDIA_EXTS:
                    continue

                abs_path = Path(dirpath) / fname
                try:
                    stat = abs_path.stat()
                except OSError:
                    stats["errors"] += 1
                    continue

                # Skip tiny files (likely corrupt/temp)
                if stat.st_size < 100:
                    stats["skipped"] += 1
                    continue

                # Compute relative path from upload root
                try:
                    rel_path = str(abs_path.relative_to(root))
                except ValueError:
                    # File is outside upload root — use absolute as key
                    rel_path = str(abs_path)

                # Classify
                feature, project_id = classify_path(rel_path)
                kind = "video" if ext in VIDEO_EXTS else "image"
                mime = mimetypes.guess_type(str(abs_path))[0] or ""

                # Register (idempotent)
                con = _db()
                cur = con.cursor()
                cur.execute(
                    "SELECT id FROM assets WHERE storage_backend = 'local' AND storage_key = ?",
                    (rel_path,),
                )
                existing = cur.fetchone()

                if existing:
                    # Update last_seen_at + size
                    cur.execute(
                        "UPDATE assets SET last_seen_at = datetime('now'), size_bytes = ? WHERE id = ?",
                        (stat.st_size, existing["id"]),
                    )
                    con.commit()
                    con.close()
                    stats["updated"] += 1
                else:
                    asset_id = f"a_{uuid.uuid4().hex[:20]}"
                    cur.execute(
                        """
                        INSERT INTO assets(
                            id, kind, mime, storage_backend, storage_key,
                            size_bytes, origin, source_hint, feature, project_id
                        ) VALUES (?,?,?,'local',?,?,?,?,?,?)
                        """,
                        (asset_id, kind, mime, rel_path,
                         stat.st_size, "reconcile", fname, feature, project_id),
                    )
                    con.commit()
                    con.close()
                    stats["created"] += 1
                    if verbose:
                        print(f"  + [{feature or 'other':8s}] {fname}")

    if verbose:
        print(f"[RECONCILE] Done: created={stats['created']}, "
              f"updated={stats['updated']}, skipped={stats['skipped']}, "
              f"errors={stats['errors']}")

    return stats


# ── Startup hook ───────────────────────────────────────────────────────────────

def startup_reconcile():
    """
    Run on backend startup to ensure the asset registry is populated.
    Only does a full scan if the assets table is empty (fresh DB).
    """
    _ensure_assets_table()
    count = count_assets()
    if count == 0:
        print("[ASSET_REGISTRY] Empty assets table — running reconcile from disk...")
        stats = reconcile(verbose=True)
        print(f"[ASSET_REGISTRY] Reconcile complete: {stats}")
    else:
        print(f"[ASSET_REGISTRY] {count} assets already registered")


# ── Convenience: register from ComfyUI output ─────────────────────────────────

def register_comfy_output(
    filename: str,
    dest_path: str,
    feature: str = "",
    project_id: str = "",
    user_id: str = "",
    workflow_name: str = "",
) -> str:
    """
    Register a file that was downloaded from ComfyUI.
    Call this right after saving the file to UPLOAD_DIR.

    Returns the asset_id.
    """
    root = _upload_root()
    abs_path = Path(dest_path)
    try:
        rel_path = str(abs_path.relative_to(root))
    except ValueError:
        rel_path = str(abs_path)

    size = abs_path.stat().st_size if abs_path.exists() else 0
    ext = abs_path.suffix.lower()
    kind = "video" if ext in VIDEO_EXTS else "image"
    mime = mimetypes.guess_type(str(abs_path))[0] or ""

    if not feature:
        feature = classify_filename(filename)

    return register_asset(
        storage_key=rel_path,
        kind=kind,
        mime=mime,
        size_bytes=size,
        origin="comfy",
        source_hint=f"comfy:{filename}" + (f" workflow:{workflow_name}" if workflow_name else ""),
        feature=feature,
        project_id=project_id,
        user_id=user_id,
    )
