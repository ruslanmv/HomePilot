#!/usr/bin/env python3
"""
HomePilot File Manager — Standalone visual browser + export tool for all generated media.

Scans the filesystem, ComfyUI output, database, and HomePilot API for images & videos,
then serves an HTML gallery with search, filtering, lightbox preview, and EXPORT.

Usage:
    python3 file-manager.py                     # Scan and serve on port 9090
    python3 file-manager.py --port 9090         # Custom port
    python3 file-manager.py --scan-only         # Just print files, no server
    python3 file-manager.py --comfy-url http://localhost:8188
    python3 file-manager.py --backend-url http://localhost:8000
    python3 file-manager.py --session TOKEN     # Auth for per-user files
    python3 file-manager.py --export ./backup   # Export all files to a folder
"""

import os
import sys
import json
import mimetypes
import argparse
import sqlite3
import shutil
import zipfile
import io
import time
import hashlib
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import quote, unquote
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────────────

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".gif", ".webp"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

# Filename prefixes that indicate animated/video output from ComfyUI
# (even if extension is .webp or .gif, these are videos not static images)
_ANIMATE_PREFIXES = ("animate_", "video_", "AnimateDiff_")

# Proper MIME types for video formats
_VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _classify_media_type(filename, ext):
    """Classify whether a file is an image or video based on name + extension."""
    # Always video for these extensions
    if ext in (".mp4", ".avi", ".mov", ".mkv", ".webm"):
        return "video"
    # Animated formats: check filename prefix to distinguish from static images
    if ext in (".gif", ".webp"):
        name_lower = filename.lower()
        if any(name_lower.startswith(p) for p in _ANIMATE_PREFIXES):
            return "video"
    return "image"


def _detect_project_root():
    """Auto-detect the HomePilot project root from the script location."""
    script_dir = Path(__file__).resolve().parent
    if script_dir.name == "scripts":
        return script_dir.parent
    p = Path.cwd()
    for _ in range(5):
        if (p / "backend").is_dir() and (p / "Makefile").exists():
            return p
        p = p.parent
    return Path.cwd()


def _build_scan_dirs(project_root):
    """Build scan directories based on auto-detected project root."""
    pr = project_root
    home = Path.home()
    dirs = [
        str(pr / "backend" / "data" / "uploads"),
        str(pr / "outputs"),
        str(pr / "ComfyUI" / "output"),
        str(pr / "ComfyUI" / "input"),
        "/app/data/uploads",
        "/outputs",
        "/ComfyUI/output",
        "/ComfyUI/input",
        str(home / "HomePilot" / "outputs"),
        str(home / "HomePilot" / "backend" / "data" / "uploads"),
        str(home / "ComfyUI" / "output"),
        str(home / "ComfyUI" / "input"),
    ]
    seen = set()
    unique = []
    for d in dirs:
        real = str(Path(d).resolve()) if Path(d).exists() else d
        if real not in seen:
            seen.add(real)
            unique.append(d)
    return unique


def _find_db_path(project_root):
    """Find the SQLite database in likely locations."""
    candidates = [
        project_root / "backend" / "data" / "homepilot.db",
        project_root / "backend" / "data" / "homegrok.db",
        Path("/app/data/homepilot.db"),
        Path("/app/data/homegrok.db"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return str(candidates[0])


PROJECT_ROOT = _detect_project_root()
SCAN_DIRS = _build_scan_dirs(PROJECT_ROOT)
DB_PATH = _find_db_path(PROJECT_ROOT)

# ── File Scanner ───────────────────────────────────────────────────────────────

def scan_directory(dir_path, max_depth=6):
    """Recursively scan a directory for media files."""
    found = []
    dir_path = Path(dir_path)
    if not dir_path.exists():
        return found
    try:
        for root, dirs, files in os.walk(str(dir_path)):
            depth = str(root).count(os.sep) - str(dir_path).count(os.sep)
            if depth > max_depth:
                dirs.clear()
                continue
            skip_names = {
                ".git", "node_modules", "__pycache__", "site-packages",
                ".cache", ".venv", "venv", "lib", "include",
            }
            dirs[:] = [d for d in dirs if d not in skip_names]
            for f in files:
                ext = Path(f).suffix.lower()
                if ext in MEDIA_EXTS:
                    full_path = os.path.join(root, f)
                    try:
                        stat = os.stat(full_path)
                        found.append({
                            "path": full_path,
                            "name": f,
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                            "ext": ext,
                            "type": _classify_media_type(f, ext),
                            "source": str(dir_path),
                        })
                    except OSError:
                        pass
    except PermissionError:
        pass
    return found


def scan_comfyui_api(comfy_url):
    """Query ComfyUI /history API for generated files."""
    import urllib.request
    found = []
    try:
        req = urllib.request.urlopen(f"{comfy_url}/history", timeout=5)
        data = json.loads(req.read())
    except Exception as e:
        print(f"    ComfyUI API not available: {e}")
        return found

    seen = set()
    for prompt_id, entry in data.items():
        outputs = entry.get("outputs", {})
        for node_id, node_out in outputs.items():
            for key in ("images", "gifs", "videos"):
                for item in node_out.get(key, []):
                    fname = item.get("filename", "")
                    subfolder = item.get("subfolder", "")
                    if fname and fname not in seen:
                        seen.add(fname)
                        ext = Path(fname).suffix.lower()
                        found.append({
                            "path": f"{comfy_url}/view?filename={quote(fname)}&type=output"
                                    + (f"&subfolder={quote(subfolder)}" if subfolder else ""),
                            "name": fname,
                            "size": 0,
                            "modified": 0,
                            "ext": ext,
                            "type": _classify_media_type(f, ext),
                            "source": "ComfyUI API",
                            "is_remote": True,
                        })
    return found


def scan_database():
    """Check HomePilot database for file references."""
    found = []
    if not os.path.exists(DB_PATH):
        return found
    upload_root = str(PROJECT_ROOT / "backend" / "data" / "uploads")
    if not os.path.isdir(upload_root):
        upload_root = "/app/data/uploads"
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, rel_path, mime, size_bytes, original_name, project_id, created_at FROM file_assets")
        for row in cursor.fetchall():
            fid, rel_path, mime, size, orig_name, proj_id, created = row
            if rel_path:
                full_path = os.path.join(upload_root, rel_path)
                ext = Path(rel_path).suffix.lower()
                if ext in MEDIA_EXTS:
                    display_name = orig_name or os.path.basename(rel_path)
                    found.append({
                        "path": full_path,
                        "name": display_name,
                        "size": size or 0,
                        "modified": 0,
                        "ext": ext,
                        # Was ``_classify_media_type(f, ext)`` — ``f`` was never
                        # defined in this scope and swallowed every DB row
                        # with "name 'f' is not defined". Use the display
                        # name we already computed.
                        "type": _classify_media_type(display_name, ext),
                        "source": f"DB (project: {proj_id or 'none'})",
                    })
        conn.close()
    except Exception as e:
        print(f"    Database error: {e}")
    return found


def scan_backend_api(backend_url, session_token=None):
    """Query HomePilot backend API for projects and their avatar/media files."""
    import urllib.request
    found = []
    headers = {}
    if session_token:
        headers["Cookie"] = f"homepilot_session={session_token}"
    try:
        req = urllib.request.Request(f"{backend_url}/projects", headers=headers)
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        projects_list = data.get("projects", data) if isinstance(data, dict) else data
    except Exception as e:
        print(f"    Backend API error: {e}")
        return found

    print(f"    Found {len(projects_list)} project(s)")

    for proj in projects_list:
        pid = proj.get("id", "")
        pname = proj.get("name", "unnamed")
        ptype = proj.get("project_type", "")
        if ptype != "persona":
            continue
        appearance = proj.get("persona_appearance") or {}

        # Selected avatar / thumbnail
        for fname_path in [appearance.get("selected_thumb_filename", ""),
                           appearance.get("selected_filename", "")]:
            if not fname_path:
                continue
            basename = os.path.basename(fname_path)
            ext = Path(basename).suffix.lower()
            if ext in MEDIA_EXTS:
                file_url = f"{backend_url}/files/{fname_path}"
                if session_token:
                    file_url += f"?token={session_token}"
                found.append({
                    "path": file_url, "name": basename, "size": 0,
                    "modified": proj.get("updated_at", 0), "ext": ext,
                    "type": "image", "source": f"Project: {pname}",
                    "is_remote": True,
                })

        # Avatar set images
        for s in appearance.get("sets") or []:
            for img in s.get("images") or []:
                url = img.get("url", "")
                if not url:
                    continue
                basename = os.path.basename(url.split("?")[0])
                ext = Path(basename).suffix.lower()
                if ext not in MEDIA_EXTS:
                    continue
                full_url = f"{backend_url}{url}" if url.startswith("/") else url
                if session_token:
                    full_url += ("&" if "?" in full_url else "?") + f"token={session_token}"
                found.append({
                    "path": full_url, "name": basename, "size": 0,
                    "modified": proj.get("updated_at", 0), "ext": ext,
                    "type": "image", "source": f"Avatar Set: {pname}",
                    "is_remote": True,
                })

        # Outfit images
        for outfit in appearance.get("outfits") or []:
            for img in outfit.get("images") or []:
                url = img.get("url", "")
                if not url:
                    continue
                basename = os.path.basename(url.split("?")[0])
                ext = Path(basename).suffix.lower()
                if ext not in MEDIA_EXTS:
                    continue
                full_url = f"{backend_url}{url}" if url.startswith("/") else url
                if session_token:
                    full_url += ("&" if "?" in full_url else "?") + f"token={session_token}"
                found.append({
                    "path": full_url, "name": basename, "size": 0,
                    "modified": proj.get("updated_at", 0), "ext": ext,
                    "type": "image",
                    "source": f"Outfit: {pname} / {outfit.get('label', '?')}",
                    "is_remote": True,
                })
    return found


# ── Export ─────────────────────────────────────────────────────────────────────

def export_files(all_files, export_path, as_zip=False):
    """Export all found files to a folder or zip archive."""
    import urllib.request

    export_dir = Path(export_path)
    if as_zip:
        zip_path = export_dir.with_suffix(".zip") if not str(export_dir).endswith(".zip") else export_dir
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"\n  Exporting {len(all_files)} files to {zip_path} ...")
        exported = 0
        failed = 0
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            for f in all_files:
                is_remote = f.get("is_remote", False)
                # Organize inside zip by source category
                source_folder = _sanitize_folder(f["source"])
                arc_name = f"{source_folder}/{f['name']}"
                # Avoid duplicates in zip
                existing = set(zf.namelist())
                if arc_name in existing:
                    stem = Path(f["name"]).stem
                    ext = Path(f["name"]).suffix
                    arc_name = f"{source_folder}/{stem}_{hashlib.md5(f['path'].encode()).hexdigest()[:6]}{ext}"

                try:
                    if is_remote:
                        data = urllib.request.urlopen(f["path"], timeout=30).read()
                        zf.writestr(arc_name, data)
                    else:
                        if os.path.isfile(f["path"]):
                            zf.write(f["path"], arc_name)
                        else:
                            print(f"    SKIP {f['name']} (file not on disk)")
                            failed += 1
                            continue
                    exported += 1
                    print(f"    + {arc_name}")
                except Exception as e:
                    print(f"    FAIL {f['name']}: {e}")
                    failed += 1

        size = zip_path.stat().st_size / (1024 * 1024)
        print(f"\n  Export complete: {exported} files, {failed} failed")
        print(f"  Archive: {zip_path} ({size:.1f} MB)")
        return str(zip_path)
    else:
        # Export to folder
        export_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n  Exporting {len(all_files)} files to {export_dir}/ ...")
        exported = 0
        failed = 0
        for f in all_files:
            is_remote = f.get("is_remote", False)
            source_folder = _sanitize_folder(f["source"])
            dest_dir = export_dir / source_folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / f["name"]
            # Handle name collisions
            if dest_file.exists():
                stem = Path(f["name"]).stem
                ext = Path(f["name"]).suffix
                dest_file = dest_dir / f"{stem}_{hashlib.md5(f['path'].encode()).hexdigest()[:6]}{ext}"

            try:
                if is_remote:
                    data = urllib.request.urlopen(f["path"], timeout=30).read()
                    dest_file.write_bytes(data)
                else:
                    if os.path.isfile(f["path"]):
                        shutil.copy2(f["path"], str(dest_file))
                    else:
                        print(f"    SKIP {f['name']} (file not on disk)")
                        failed += 1
                        continue
                exported += 1
                print(f"    + {dest_file}")
            except Exception as e:
                print(f"    FAIL {f['name']}: {e}")
                failed += 1

        print(f"\n  Export complete: {exported} files, {failed} failed")
        print(f"  Folder: {export_dir}/")
        return str(export_dir)


def _sanitize_folder(source_name):
    """Convert a source name to a safe folder name."""
    safe = source_name.replace("/", "_").replace("\\", "_").replace(":", "_")
    safe = "".join(c for c in safe if c.isalnum() or c in "._- ")
    return safe[:80] or "other"


def export_to_zip_bytes(all_files):
    """Create a zip in memory and return the bytes (for HTTP download)."""
    import urllib.request
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        existing = set()
        for f in all_files:
            source_folder = _sanitize_folder(f["source"])
            arc_name = f"{source_folder}/{f['name']}"
            if arc_name in existing:
                stem = Path(f["name"]).stem
                ext = Path(f["name"]).suffix
                arc_name = f"{source_folder}/{stem}_{hashlib.md5(f['path'].encode()).hexdigest()[:6]}{ext}"
            existing.add(arc_name)
            try:
                if f.get("is_remote"):
                    data = urllib.request.urlopen(f["path"], timeout=30).read()
                    zf.writestr(arc_name, data)
                elif os.path.isfile(f["path"]):
                    zf.write(f["path"], arc_name)
            except Exception:
                pass
    return buf.getvalue()


# ── HTML Generator ─────────────────────────────────────────────────────────────

def generate_html(all_files):
    """Generate a visual HTML gallery page with export button."""

    by_source = {}
    for f in all_files:
        by_source.setdefault(f["source"], []).append(f)
    for src in by_source:
        by_source[src].sort(key=lambda x: x["modified"], reverse=True)

    total_images = sum(1 for f in all_files if f["type"] == "image")
    total_videos = sum(1 for f in all_files if f["type"] == "video")
    total_size = sum(f["size"] for f in all_files)

    def fmt_size(b):
        for u in ["B", "KB", "MB", "GB"]:
            if b < 1024:
                return f"{b:.1f} {u}"
            b /= 1024
        return f"{b:.1f} TB"

    def fmt_time(ts):
        if ts == 0:
            return ""
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

    cards = ""
    for source, files in sorted(by_source.items()):
        cards += f"""
        <div class="source-group">
          <h2 class="source-header">
            <span class="folder-icon"></span> {source}
            <span class="badge">{len(files)}</span>
          </h2>
          <div class="file-grid">"""
        for f in files:
            is_remote = f.get("is_remote", False)
            fp = f["path"]
            if f["type"] == "video" and f["ext"] in (".mp4", ".webm", ".avi", ".mov", ".mkv"):
                mime = _VIDEO_MIME.get(f["ext"], "video/mp4")
                tag = f'<video controls preload="metadata" class="media-preview"><source src="/serve?path={quote(fp)}" type="{mime}"></video>'
            else:
                src_url = fp if is_remote else f"/serve?path={quote(fp)}"
                tag = f'<img src="{src_url}" class="media-preview" loading="lazy" alt="{f["name"]}">'
            dl_url = fp if is_remote else f"/serve?path={quote(fp)}"
            cards += f"""
            <div class="file-card" data-type="{f['type']}" data-name="{f['name'].lower()}">
              <div class="media-container">
                {tag}
                <span class="type-badge {'vb' if f['type']=='video' else 'ib'}">{f['ext']}</span>
                <a class="dl-btn" href="{dl_url}" download="{f['name']}" title="Download">&#8681;</a>
              </div>
              <div class="file-info">
                <div class="file-name" title="{f['path']}">{f['name']}</div>
                <div class="file-meta"><span>{fmt_size(f['size'])}</span><span>{fmt_time(f['modified'])}</span></div>
              </div>
            </div>"""
        cards += "</div></div>"

    empty = "" if all_files else '<div class="empty"><h2>No media files found</h2><p>Start ComfyUI and generate images or videos. They will appear here when you refresh.</p></div>'

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HomePilot File Manager</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f1117;color:#e1e4e8;min-height:100vh}}
.hdr{{background:linear-gradient(135deg,#1a1d2e,#0d1117);border-bottom:1px solid #30363d;padding:20px 28px;position:sticky;top:0;z-index:100}}
.hdr h1{{font-size:22px;font-weight:700;margin-bottom:10px}}.hdr h1 span{{color:#58a6ff}}
.stats{{display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap}}
.stat{{background:#21262d;padding:6px 14px;border-radius:8px;font-size:13px}}.stat b{{color:#58a6ff}}
.ctrls{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
.search{{flex:1;min-width:180px;max-width:360px;padding:7px 14px;background:#0d1117;border:1px solid #30363d;border-radius:8px;color:#e1e4e8;font-size:13px}}
.search:focus{{border-color:#58a6ff;outline:none}}
.fbtn{{padding:7px 14px;background:#21262d;border:1px solid #30363d;border-radius:8px;color:#e1e4e8;cursor:pointer;font-size:13px;transition:.2s}}
.fbtn:hover{{background:#30363d}}.fbtn.on{{background:#1f6feb;border-color:#58a6ff}}
.export-btn{{padding:7px 18px;background:#238636;border:1px solid #2ea043;border-radius:8px;color:white;cursor:pointer;font-size:13px;font-weight:600;transition:.2s}}
.export-btn:hover{{background:#2ea043}}
.export-btn:disabled{{opacity:.5;cursor:wait}}
.cnt{{padding:20px 28px}}
.source-group{{margin-bottom:28px}}
.source-header{{font-size:16px;font-weight:600;margin-bottom:12px;padding-bottom:6px;border-bottom:1px solid #21262d;display:flex;align-items:center;gap:8px}}
.folder-icon::before{{content:"\\1F4C2";font-size:18px}}
.badge{{background:#1f6feb;color:#fff;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:500}}
.file-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}}
.file-card{{background:#161b22;border:1px solid #21262d;border-radius:10px;overflow:hidden;transition:.2s}}
.file-card:hover{{border-color:#58a6ff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.4)}}
.media-container{{position:relative;width:100%;padding-top:75%;background:#0d1117;overflow:hidden}}
.media-preview{{position:absolute;top:0;left:0;width:100%;height:100%;object-fit:contain;cursor:pointer}}
.media-preview:hover{{object-fit:cover}}
.type-badge{{position:absolute;top:6px;right:6px;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;text-transform:uppercase}}
.ib{{background:rgba(56,139,253,.8)}}.vb{{background:rgba(238,88,67,.8)}}
.dl-btn{{position:absolute;bottom:6px;right:6px;background:rgba(0,0,0,.7);color:#58a6ff;padding:4px 8px;border-radius:4px;font-size:16px;text-decoration:none;opacity:0;transition:.2s}}
.file-card:hover .dl-btn{{opacity:1}}
.file-info{{padding:10px}}.file-name{{font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:3px}}
.file-meta{{display:flex;justify-content:space-between;font-size:10px;color:#8b949e}}
.empty{{text-align:center;padding:60px 20px;color:#8b949e}}.empty h2{{font-size:22px;margin-bottom:10px;color:#e1e4e8}}.empty p{{font-size:14px;max-width:500px;margin:0 auto}}
.lb{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.92);z-index:1000;justify-content:center;align-items:center}}
.lb.on{{display:flex}}.lb img,.lb video{{max-width:85%;max-height:85%;object-fit:contain;border-radius:8px}}
.lb-nav{{position:fixed;top:50%;transform:translateY(-50%);font-size:36px;color:rgba(255,255,255,.7);cursor:pointer;padding:16px 12px;z-index:1001;user-select:none;transition:.2s}}
.lb-nav:hover{{color:#fff;background:rgba(255,255,255,.1);border-radius:8px}}
.lb-prev{{left:12px}}.lb-next{{right:12px}}
.lb-info{{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,.8);padding:6px 18px;border-radius:8px;font-size:13px}}
.lb-counter{{position:fixed;top:16px;right:20px;background:rgba(0,0,0,.7);padding:4px 14px;border-radius:8px;font-size:13px;color:#8b949e;z-index:1001}}
.toast{{position:fixed;top:20px;right:20px;background:#238636;color:white;padding:12px 20px;border-radius:8px;font-size:14px;z-index:2000;display:none;box-shadow:0 4px 12px rgba(0,0,0,.5)}}
.toast.show{{display:block;animation:fadeInOut 3s ease}}
@keyframes fadeInOut{{0%{{opacity:0}}10%{{opacity:1}}80%{{opacity:1}}100%{{opacity:0}}}}
</style></head><body>
<div class="hdr">
  <h1><span>HomePilot</span> File Manager</h1>
  <div class="stats">
    <div class="stat">Total: <b>{len(all_files)}</b> files</div>
    <div class="stat">Images: <b>{total_images}</b></div>
    <div class="stat">Videos: <b>{total_videos}</b></div>
    <div class="stat">Size: <b>{fmt_size(total_size)}</b></div>
    <div class="stat">Sources: <b>{len(by_source)}</b></div>
  </div>
  <div class="ctrls">
    <input type="text" class="search" placeholder="Search files..." oninput="filt()">
    <button class="fbtn on" onclick="sf('all',this)">All</button>
    <button class="fbtn" onclick="sf('image',this)">Images</button>
    <button class="fbtn" onclick="sf('video',this)">Videos</button>
    <button class="export-btn" onclick="doExport()" id="exportBtn">&#8615; Export All as ZIP</button>
    <button class="export-btn" style="background:#1f6feb;border-color:#388bfd" onclick="doExportFiltered()" id="exportFiltBtn">&#8615; Export Filtered</button>
  </div>
</div>
<div class="cnt">{empty}{cards}</div>
<div class="lb" id="lb"><div class="lb-nav lb-prev" onclick="navLb(-1,event)">&#10094;</div><div id="lbc" onclick="clb()"></div><div class="lb-nav lb-next" onclick="navLb(1,event)">&#10095;</div><div class="lb-info" id="lbi"></div><div class="lb-counter" id="lbcnt"></div></div>
<div class="toast" id="toast"></div>
<script>
let cf='all', lbIdx=-1;
function sf(t,b){{cf=t;document.querySelectorAll('.fbtn').forEach(x=>x.classList.remove('on'));b.classList.add('on');filt()}}
function filt(){{const s=document.querySelector('.search').value.toLowerCase();document.querySelectorAll('.file-card').forEach(c=>{{const n=c.dataset.name,t=c.dataset.type;c.style.display=(!s||n.includes(s))&&(cf==='all'||t===cf)?'':'none'}})}}
function getVisibleCards(){{return [...document.querySelectorAll('.file-card')].filter(c=>c.style.display!=='none')}}
function showLb(idx){{
  const cards=getVisibleCards();
  if(idx<0||idx>=cards.length)return;
  lbIdx=idx;
  const card=cards[idx],el=card.querySelector('.media-preview');
  const lb=document.getElementById('lb'),c=document.getElementById('lbc'),i=document.getElementById('lbi'),cnt=document.getElementById('lbcnt');
  const v=lb.querySelector('video');if(v)v.pause();
  if(el.tagName==='IMG')c.innerHTML=`<img src="${{el.src}}" alt="" onclick="event.stopPropagation()">`;
  else if(el.tagName==='VIDEO')c.innerHTML=`<video controls autoplay onclick="event.stopPropagation()"><source src="${{el.querySelector('source').src}}"></video>`;
  else c.innerHTML=`<img src="${{el.src||el.querySelector('source')?.src}}" alt="" onclick="event.stopPropagation()">`;
  i.textContent=card.querySelector('.file-name').title||card.querySelector('.file-name').textContent;
  cnt.textContent=`${{idx+1}} / ${{cards.length}}`;
  lb.classList.add('on');
}}
function navLb(dir,evt){{
  if(evt)evt.stopPropagation();
  if(lbIdx<0)return;
  const cards=getVisibleCards();
  let next=lbIdx+dir;
  if(next<0)next=cards.length-1;
  if(next>=cards.length)next=0;
  showLb(next);
}}
document.querySelectorAll('.media-preview').forEach(el=>{{el.addEventListener('click',e=>{{
  e.stopPropagation();
  const card=el.closest('.file-card');
  const cards=getVisibleCards();
  const idx=cards.indexOf(card);
  showLb(idx>=0?idx:0);
}})}});
function clb(){{const lb=document.getElementById('lb');lb.classList.remove('on');const v=lb.querySelector('video');if(v)v.pause();lbIdx=-1}}
document.addEventListener('keydown',e=>{{
  if(lbIdx<0)return;
  if(e.key==='Escape')clb();
  else if(e.key==='ArrowLeft'||e.key==='a'){{e.preventDefault();navLb(-1)}}
  else if(e.key==='ArrowRight'||e.key==='d'){{e.preventDefault();navLb(1)}}
}});
function toast(msg){{const t=document.getElementById('toast');t.textContent=msg;t.classList.remove('show');void t.offsetWidth;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3000)}}
function doExport(){{
  const btn=document.getElementById('exportBtn');
  btn.disabled=true;btn.textContent='Preparing ZIP...';
  fetch('/export-zip').then(r=>{{if(!r.ok)throw new Error('Export failed');return r.blob()}}).then(b=>{{
    const a=document.createElement('a');a.href=URL.createObjectURL(b);
    a.download='homepilot-export-'+new Date().toISOString().slice(0,10)+'.zip';
    a.click();URL.revokeObjectURL(a.href);
    toast('Export downloaded!');
  }}).catch(e=>toast('Export error: '+e.message)).finally(()=>{{btn.disabled=false;btn.textContent='\\u2197 Export All as ZIP'}})
}}
function doExportFiltered(){{
  const visible=[];
  document.querySelectorAll('.file-card').forEach(c=>{{if(c.style.display!=='none')visible.push(c.dataset.name)}});
  const btn=document.getElementById('exportFiltBtn');
  btn.disabled=true;btn.textContent='Preparing...';
  fetch('/export-zip?names='+encodeURIComponent(visible.join('|'))).then(r=>{{if(!r.ok)throw new Error('Export failed');return r.blob()}}).then(b=>{{
    const a=document.createElement('a');a.href=URL.createObjectURL(b);
    a.download='homepilot-filtered-'+new Date().toISOString().slice(0,10)+'.zip';
    a.click();URL.revokeObjectURL(a.href);toast('Filtered export downloaded!');
  }}).catch(e=>toast('Export error: '+e.message)).finally(()=>{{btn.disabled=false;btn.textContent='\\u2197 Export Filtered'}})
}}
</script></body></html>"""


# ── HTTP Server ────────────────────────────────────────────────────────────────

class FileManagerHandler(SimpleHTTPRequestHandler):
    """Serves the gallery, individual files, and export endpoints."""
    html_content = ""
    all_files = []

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            content = self.html_content.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        elif self.path.startswith("/serve?path="):
            file_path = unquote(self.path.split("path=", 1)[1])
            if os.path.isfile(file_path):
                mime, _ = mimetypes.guess_type(file_path)
                mime = mime or "application/octet-stream"
                try:
                    with open(file_path, "rb") as fh:
                        data = fh.read()
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "max-age=3600")
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as e:
                    self.send_error(500, str(e))
            else:
                self.send_error(404, "File not found")

        elif self.path.startswith("/export-zip"):
            # Optional filter by names
            names_filter = None
            if "names=" in self.path:
                raw = unquote(self.path.split("names=", 1)[1])
                names_filter = set(raw.split("|"))

            files_to_export = self.all_files
            if names_filter:
                files_to_export = [f for f in self.all_files if f["name"].lower() in names_filter]

            try:
                zip_data = export_to_zip_bytes(files_to_export)
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="homepilot-export-{datetime.now().strftime("%Y%m%d-%H%M%S")}.zip"')
                self.send_header("Content-Length", str(len(zip_data)))
                self.end_headers()
                self.wfile.write(zip_data)
            except Exception as e:
                self.send_error(500, f"Export failed: {e}")
        else:
            self.send_error(404, "Not found")

    def log_message(self, format, *args):
        if "/serve?" not in str(args):
            super().log_message(format, *args)


# ── Main ───────────────────────────────────────────────────────────────────────

def _run_scan(args):
    """Run all scanners and return deduplicated file list."""
    print("=" * 65)
    print("  HomePilot File Manager")
    print("=" * 65)
    print(f"  Project root: {PROJECT_ROOT}")
    print(f"  Database:     {DB_PATH}")
    print()

    all_files = []

    # 1. Filesystem
    scan_dirs = SCAN_DIRS + (args.extra_dirs or [])
    for d in scan_dirs:
        d = os.path.expanduser(d)
        if os.path.isdir(d):
            print(f"  Scanning: {d}")
            found = scan_directory(d)
            if found:
                print(f"    Found {len(found)} media file(s)")
                all_files.extend(found)
            else:
                print(f"    (no media files)")
        else:
            print(f"  Skipped: {d} (not found)")

    # 2. Database
    print(f"\n  Database: {DB_PATH} {'(exists)' if os.path.exists(DB_PATH) else '(not found)'}")
    db_files = scan_database()
    if db_files:
        print(f"    Found {len(db_files)} file reference(s)")
        all_files.extend(db_files)
    else:
        print("    No file references in database")

    # 3. ComfyUI API
    comfy_url = args.comfy_url or os.environ.get("COMFY_BASE_URL")
    if comfy_url:
        print(f"\n  ComfyUI API: {comfy_url}")
        api_files = scan_comfyui_api(comfy_url)
        if api_files:
            print(f"    Found {len(api_files)} file(s) in history")
            all_files.extend(api_files)
    else:
        for url in ["http://localhost:8188", "http://comfyui:8188"]:
            print(f"\n  Trying ComfyUI API: {url}")
            api_files = scan_comfyui_api(url)
            if api_files:
                print(f"    Found {len(api_files)} file(s) in history")
                all_files.extend(api_files)
                break
            if url == "http://localhost:8188":
                try:
                    import urllib.request
                    urllib.request.urlopen(f"{url}/system_stats", timeout=2)
                    print("    ComfyUI running but no history yet")
                    break
                except Exception:
                    pass

    # 4. Backend API
    backend_url = args.backend_url or os.environ.get("BACKEND_URL")
    if not backend_url:
        try:
            import urllib.request
            urllib.request.urlopen("http://localhost:8000/health", timeout=2)
            backend_url = "http://localhost:8000"
        except Exception:
            pass
    if backend_url:
        print(f"\n  HomePilot API: {backend_url}")
        backend_files = scan_backend_api(backend_url, session_token=args.session)
        if backend_files:
            print(f"    Found {len(backend_files)} media file(s) in projects")
            all_files.extend(backend_files)
        else:
            print("    No media files in projects")
    else:
        print("\n  HomePilot API: not running (skipped)")

    # Deduplicate
    seen = set()
    unique = []
    for f in all_files:
        if f["path"] not in seen:
            seen.add(f["path"])
            unique.append(f)

    print(f"\n  Total unique files: {len(unique)}\n")
    return unique


def main():
    parser = argparse.ArgumentParser(description="HomePilot File Manager — browse & export generated media")
    parser.add_argument("--port", type=int, default=9090, help="Server port (default: 9090)")
    parser.add_argument("--scan-only", action="store_true", help="Print files and exit")
    parser.add_argument("--comfy-url", default=None, help="ComfyUI URL")
    parser.add_argument("--backend-url", default=None, help="HomePilot backend URL")
    parser.add_argument("--session", default=None, help="Session token for authenticated access")
    parser.add_argument("--extra-dirs", nargs="*", default=[], help="Extra directories to scan")
    parser.add_argument("--export", default=None, metavar="PATH",
                        help="Export all files to a folder (or .zip if path ends in .zip)")
    args = parser.parse_args()

    all_files = _run_scan(args)

    # --scan-only: just print
    if args.scan_only:
        print("-" * 65)
        for f in sorted(all_files, key=lambda x: x["name"]):
            sz = f"{f['size']/1024:.1f}KB" if f["size"] > 0 else "??KB"
            print(f"  [{f['type']:5s}] {f['name']:40s} {sz:>10s}  ({f['source']})")
        print("-" * 65)
        print(f"  {len(all_files)} file(s) total")
        return

    # --export: save to disk
    if args.export:
        as_zip = args.export.endswith(".zip")
        export_files(all_files, args.export, as_zip=as_zip)
        return

    # Default: start web server
    html = generate_html(all_files)
    FileManagerHandler.html_content = html
    FileManagerHandler.all_files = all_files

    server = HTTPServer(("0.0.0.0", args.port), FileManagerHandler)
    print("=" * 65)
    print(f"  File Manager: http://localhost:{args.port}")
    print(f"  Export ZIP:    http://localhost:{args.port}/export-zip")
    print(f"  Press Ctrl+C to stop")
    print("=" * 65)
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
