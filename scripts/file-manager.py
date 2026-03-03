#!/usr/bin/env python3
"""
HomePilot File Manager — Standalone visual browser for all generated media.

Scans the filesystem, ComfyUI output, and HomePilot uploads for images & videos,
then serves an HTML gallery you can open in your browser.

Usage:
    python3 file-manager.py                     # Scan and serve on port 9090
    python3 file-manager.py --port 9090         # Custom port
    python3 file-manager.py --scan-only         # Just print files, no server
    python3 file-manager.py --comfy-url http://localhost:8188  # Query ComfyUI API too
"""

import os
import sys
import json
import mimetypes
import argparse
import sqlite3
import base64
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import quote, unquote
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────────────

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".gif"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


def _detect_project_root():
    """Auto-detect the HomePilot project root from the script location."""
    # scripts/file-manager.py → parent is scripts/, grandparent is project root
    script_dir = Path(__file__).resolve().parent
    if script_dir.name == "scripts":
        return script_dir.parent
    # Fallback: walk up looking for Makefile or backend/
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
        # Project-relative paths (works for both local dev & Docker)
        str(pr / "backend" / "data" / "uploads"),
        str(pr / "outputs"),
        str(pr / "ComfyUI" / "output"),
        str(pr / "ComfyUI" / "input"),
        # Docker paths
        "/app/data/uploads",
        "/outputs",
        "/ComfyUI/output",
        "/ComfyUI/input",
        # Home-relative paths
        str(home / "HomePilot" / "outputs"),
        str(home / "HomePilot" / "backend" / "data" / "uploads"),
        str(home / "ComfyUI" / "output"),
        str(home / "ComfyUI" / "input"),
    ]
    # Deduplicate while preserving order
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
    # Return best guess even if missing
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
            # Skip deep directories and known non-media dirs
            depth = str(root).count(os.sep) - str(dir_path).count(os.sep)
            if depth > max_depth:
                dirs.clear()
                continue

            # Skip non-relevant directories
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
                            "type": "video" if ext in VIDEO_EXTS and ext != ".gif" else "image",
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
        print(f"  ComfyUI API not available: {e}")
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
                            "type": "video" if ext in VIDEO_EXTS and ext != ".gif" else "image",
                            "source": "ComfyUI API",
                            "is_remote": True,
                        })

    return found


def scan_database():
    """Check HomePilot database for file references."""
    found = []
    if not os.path.exists(DB_PATH):
        return found

    # Determine upload root from project root
    upload_root = str(PROJECT_ROOT / "backend" / "data" / "uploads")
    if not os.path.isdir(upload_root):
        upload_root = "/app/data/uploads"

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Check file_assets table
        cursor.execute("SELECT id, rel_path, mime, size_bytes, original_name, project_id, created_at FROM file_assets")
        for row in cursor.fetchall():
            fid, rel_path, mime, size, orig_name, proj_id, created = row
            if rel_path:
                full_path = os.path.join(upload_root, rel_path)
                ext = Path(rel_path).suffix.lower()
                if ext in MEDIA_EXTS:
                    found.append({
                        "path": full_path,
                        "name": orig_name or os.path.basename(rel_path),
                        "size": size or 0,
                        "modified": 0,
                        "ext": ext,
                        "type": "video" if ext in VIDEO_EXTS and ext != ".gif" else "image",
                        "source": f"DB (project: {proj_id or 'none'})",
                    })

        conn.close()
    except Exception as e:
        print(f"  Database error: {e}")

    return found


def scan_backend_api(backend_url, session_token=None):
    """Query HomePilot backend API for projects and their avatar/media files."""
    import urllib.request
    found = []

    headers = {}
    if session_token:
        headers["Cookie"] = f"homepilot_session={session_token}"

    # 1. Get projects list
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

        # Extract avatar/appearance images from persona projects
        if ptype == "persona":
            appearance = proj.get("persona_appearance") or {}

            # Selected avatar thumbnail
            thumb = appearance.get("selected_thumb_filename") or ""
            selected = appearance.get("selected_filename") or ""

            for fname_path in [thumb, selected]:
                if fname_path:
                    basename = os.path.basename(fname_path)
                    ext = Path(basename).suffix.lower()
                    if ext in MEDIA_EXTS:
                        # Build the backend /files/ URL for serving
                        file_url = f"{backend_url}/files/{fname_path}"
                        if session_token:
                            file_url += f"?token={session_token}"
                        found.append({
                            "path": file_url,
                            "name": basename,
                            "size": 0,
                            "modified": proj.get("updated_at", 0),
                            "ext": ext,
                            "type": "image",
                            "source": f"Project: {pname}",
                            "is_remote": True,
                        })

            # All images in avatar sets
            for s in appearance.get("sets") or []:
                for img in s.get("images") or []:
                    url = img.get("url", "")
                    if url:
                        basename = os.path.basename(url.split("?")[0])
                        ext = Path(basename).suffix.lower()
                        if ext not in MEDIA_EXTS:
                            continue
                        # Make absolute URL
                        if url.startswith("/"):
                            full_url = f"{backend_url}{url}"
                        else:
                            full_url = url
                        if session_token and "?" not in full_url:
                            full_url += f"?token={session_token}"
                        elif session_token:
                            full_url += f"&token={session_token}"
                        found.append({
                            "path": full_url,
                            "name": basename,
                            "size": 0,
                            "modified": proj.get("updated_at", 0),
                            "ext": ext,
                            "type": "image",
                            "source": f"Avatar Set: {pname}",
                            "is_remote": True,
                        })

            # Outfit images
            for outfit in appearance.get("outfits") or []:
                for img in outfit.get("images") or []:
                    url = img.get("url", "")
                    if url:
                        basename = os.path.basename(url.split("?")[0])
                        ext = Path(basename).suffix.lower()
                        if ext not in MEDIA_EXTS:
                            continue
                        if url.startswith("/"):
                            full_url = f"{backend_url}{url}"
                        else:
                            full_url = url
                        if session_token and "?" not in full_url:
                            full_url += f"?token={session_token}"
                        elif session_token:
                            full_url += f"&token={session_token}"
                        found.append({
                            "path": full_url,
                            "name": basename,
                            "size": 0,
                            "modified": proj.get("updated_at", 0),
                            "ext": ext,
                            "type": "image",
                            "source": f"Outfit: {pname} / {outfit.get('label', '?')}",
                            "is_remote": True,
                        })

    return found


# ── HTML Generator ─────────────────────────────────────────────────────────────

def generate_html(all_files):
    """Generate a visual HTML gallery page."""

    # Group files by source directory
    by_source = {}
    for f in all_files:
        src = f["source"]
        by_source.setdefault(src, []).append(f)

    # Sort each group by modified time (newest first)
    for src in by_source:
        by_source[src].sort(key=lambda x: x["modified"], reverse=True)

    # Count stats
    total_images = sum(1 for f in all_files if f["type"] == "image")
    total_videos = sum(1 for f in all_files if f["type"] == "video")
    total_size = sum(f["size"] for f in all_files)

    def format_size(b):
        for unit in ["B", "KB", "MB", "GB"]:
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"

    def format_time(ts):
        if ts == 0:
            return "Unknown"
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    # Build file cards HTML
    cards_html = ""
    for source, files in sorted(by_source.items()):
        cards_html += f"""
        <div class="source-group">
            <h2 class="source-header">
                <span class="source-icon">&#128193;</span> {source}
                <span class="badge">{len(files)} files</span>
            </h2>
            <div class="file-grid">
        """
        for f in files:
            is_remote = f.get("is_remote", False)
            file_path = f["path"]

            if f["type"] == "video" and f["ext"] != ".gif":
                media_tag = f"""
                    <video controls preload="metadata" class="media-preview">
                        <source src="/serve?path={quote(file_path)}" type="video/{f['ext'].lstrip('.')}">
                        Video not supported
                    </video>
                """
            else:
                src_url = file_path if is_remote else f"/serve?path={quote(file_path)}"
                media_tag = f'<img src="{src_url}" class="media-preview" loading="lazy" alt="{f["name"]}">'

            cards_html += f"""
                <div class="file-card" data-type="{f['type']}" data-name="{f['name'].lower()}">
                    <div class="media-container">
                        {media_tag}
                        <span class="type-badge {'video-badge' if f['type'] == 'video' else 'image-badge'}">{f['ext']}</span>
                    </div>
                    <div class="file-info">
                        <div class="file-name" title="{f['path']}">{f['name']}</div>
                        <div class="file-meta">
                            <span>{format_size(f['size'])}</span>
                            <span>{format_time(f['modified'])}</span>
                        </div>
                    </div>
                </div>
            """

        cards_html += """
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HomePilot File Manager</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f1117;
            color: #e1e4e8;
            min-height: 100vh;
        }}

        .header {{
            background: linear-gradient(135deg, #1a1d2e 0%, #0d1117 100%);
            border-bottom: 1px solid #30363d;
            padding: 24px 32px;
            position: sticky;
            top: 0;
            z-index: 100;
        }}

        .header h1 {{
            font-size: 24px;
            font-weight: 700;
            margin-bottom: 12px;
        }}

        .header h1 span {{ color: #58a6ff; }}

        .stats {{
            display: flex;
            gap: 24px;
            margin-bottom: 16px;
        }}

        .stat {{
            background: #21262d;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 14px;
        }}

        .stat strong {{ color: #58a6ff; }}

        .controls {{
            display: flex;
            gap: 12px;
            align-items: center;
            flex-wrap: wrap;
        }}

        .search-box {{
            flex: 1;
            min-width: 200px;
            max-width: 400px;
            padding: 8px 16px;
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 8px;
            color: #e1e4e8;
            font-size: 14px;
        }}

        .search-box:focus {{ border-color: #58a6ff; outline: none; }}

        .filter-btn {{
            padding: 8px 16px;
            background: #21262d;
            border: 1px solid #30363d;
            border-radius: 8px;
            color: #e1e4e8;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }}

        .filter-btn:hover {{ background: #30363d; }}
        .filter-btn.active {{ background: #1f6feb; border-color: #58a6ff; }}

        .container {{ padding: 24px 32px; }}

        .source-group {{ margin-bottom: 32px; }}

        .source-header {{
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid #21262d;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .source-icon {{ font-size: 20px; }}

        .badge {{
            background: #1f6feb;
            color: white;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
        }}

        .file-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
            gap: 16px;
        }}

        .file-card {{
            background: #161b22;
            border: 1px solid #21262d;
            border-radius: 12px;
            overflow: hidden;
            transition: all 0.2s;
        }}

        .file-card:hover {{
            border-color: #58a6ff;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        }}

        .media-container {{
            position: relative;
            width: 100%;
            padding-top: 75%;
            background: #0d1117;
            overflow: hidden;
        }}

        .media-preview {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            object-fit: contain;
            cursor: pointer;
        }}

        .media-preview:hover {{ object-fit: cover; }}

        .type-badge {{
            position: absolute;
            top: 8px;
            right: 8px;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .image-badge {{ background: rgba(56, 139, 253, 0.8); }}
        .video-badge {{ background: rgba(238, 88, 67, 0.8); }}

        .file-info {{ padding: 12px; }}

        .file-name {{
            font-size: 13px;
            font-weight: 500;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-bottom: 4px;
        }}

        .file-meta {{
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: #8b949e;
        }}

        .empty-state {{
            text-align: center;
            padding: 80px 20px;
            color: #8b949e;
        }}

        .empty-state h2 {{ font-size: 24px; margin-bottom: 12px; color: #e1e4e8; }}
        .empty-state p {{ font-size: 16px; line-height: 1.6; max-width: 600px; margin: 0 auto; }}

        /* Lightbox */
        .lightbox {{
            display: none;
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            background: rgba(0,0,0,0.9);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            cursor: pointer;
        }}

        .lightbox.active {{ display: flex; }}

        .lightbox img, .lightbox video {{
            max-width: 90%;
            max-height: 90%;
            object-fit: contain;
            border-radius: 8px;
        }}

        .lightbox-info {{
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0,0,0,0.8);
            padding: 8px 20px;
            border-radius: 8px;
            font-size: 14px;
            color: #e1e4e8;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1><span>HomePilot</span> File Manager</h1>
        <div class="stats">
            <div class="stat">Total: <strong>{len(all_files)}</strong> files</div>
            <div class="stat">Images: <strong>{total_images}</strong></div>
            <div class="stat">Videos: <strong>{total_videos}</strong></div>
            <div class="stat">Size: <strong>{format_size(total_size)}</strong></div>
            <div class="stat">Sources: <strong>{len(by_source)}</strong> locations</div>
        </div>
        <div class="controls">
            <input type="text" class="search-box" placeholder="Search files..." oninput="filterFiles()">
            <button class="filter-btn active" onclick="setFilter('all', this)">All</button>
            <button class="filter-btn" onclick="setFilter('image', this)">Images</button>
            <button class="filter-btn" onclick="setFilter('video', this)">Videos</button>
        </div>
    </div>

    <div class="container">
        {"" if all_files else '<div class="empty-state"><h2>No media files found</h2><p>Start ComfyUI and generate some images or videos. They will appear here automatically when you refresh.</p></div>'}
        {cards_html}
    </div>

    <div class="lightbox" id="lightbox" onclick="closeLightbox()">
        <div id="lightbox-content"></div>
        <div class="lightbox-info" id="lightbox-info"></div>
    </div>

    <script>
        let currentFilter = 'all';

        function setFilter(type, btn) {{
            currentFilter = type;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            filterFiles();
        }}

        function filterFiles() {{
            const search = document.querySelector('.search-box').value.toLowerCase();
            document.querySelectorAll('.file-card').forEach(card => {{
                const name = card.dataset.name;
                const type = card.dataset.type;
                const matchSearch = !search || name.includes(search);
                const matchType = currentFilter === 'all' || type === currentFilter;
                card.style.display = (matchSearch && matchType) ? '' : 'none';
            }});
        }}

        // Lightbox
        document.querySelectorAll('.media-preview').forEach(el => {{
            el.addEventListener('click', (e) => {{
                e.stopPropagation();
                const lb = document.getElementById('lightbox');
                const content = document.getElementById('lightbox-content');
                const info = document.getElementById('lightbox-info');
                const card = el.closest('.file-card');

                if (el.tagName === 'IMG') {{
                    content.innerHTML = `<img src="${{el.src}}" alt="">`;
                }} else if (el.tagName === 'VIDEO') {{
                    content.innerHTML = `<video controls autoplay><source src="${{el.querySelector('source').src}}"></video>`;
                }}
                info.textContent = card.querySelector('.file-name').title || card.querySelector('.file-name').textContent;
                lb.classList.add('active');
            }});
        }});

        function closeLightbox() {{
            const lb = document.getElementById('lightbox');
            lb.classList.remove('active');
            const vid = lb.querySelector('video');
            if (vid) vid.pause();
        }}

        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') closeLightbox();
        }});
    </script>
</body>
</html>"""

    return html


# ── HTTP Server ────────────────────────────────────────────────────────────────

class FileManagerHandler(SimpleHTTPRequestHandler):
    """Custom handler that serves the gallery + individual media files."""

    html_content = ""
    all_files = []

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            content = self.html_content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        elif self.path.startswith("/serve?path="):
            # Serve a local file
            file_path = unquote(self.path.split("path=", 1)[1])
            if os.path.isfile(file_path):
                mime, _ = mimetypes.guess_type(file_path)
                mime = mime or "application/octet-stream"
                try:
                    with open(file_path, "rb") as f:
                        data = f.read()
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
        else:
            self.send_error(404, "Not found")

    def log_message(self, format, *args):
        # Quieter logging
        if "/serve?" not in str(args):
            super().log_message(format, *args)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="HomePilot File Manager")
    parser.add_argument("--port", type=int, default=9090, help="Server port (default: 9090)")
    parser.add_argument("--scan-only", action="store_true", help="Print files and exit (no server)")
    parser.add_argument("--comfy-url", default=None, help="ComfyUI URL (e.g., http://localhost:8188)")
    parser.add_argument("--backend-url", default=None, help="HomePilot backend URL (e.g., http://localhost:8000)")
    parser.add_argument("--session", default=None, help="HomePilot session token for authenticated access")
    parser.add_argument("--extra-dirs", nargs="*", default=[], help="Extra directories to scan")
    args = parser.parse_args()

    print("=" * 65)
    print("  HomePilot File Manager")
    print("=" * 65)
    print(f"  Project root: {PROJECT_ROOT}")
    print(f"  Database:     {DB_PATH}")
    print()

    all_files = []

    # 1. Scan filesystem directories
    scan_dirs = SCAN_DIRS + args.extra_dirs
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

    # 2. Scan database
    print(f"\n  Database: {DB_PATH} {'(exists)' if os.path.exists(DB_PATH) else '(not found)'}")
    db_files = scan_database()
    if db_files:
        print(f"    Found {len(db_files)} file reference(s)")
        all_files.extend(db_files)
    else:
        print("    No file references in database")

    # 3. Query ComfyUI API
    comfy_url = args.comfy_url or os.environ.get("COMFY_BASE_URL")
    if comfy_url:
        print(f"\n  ComfyUI API: {comfy_url}")
        api_files = scan_comfyui_api(comfy_url)
        if api_files:
            print(f"    Found {len(api_files)} file(s) in history")
            all_files.extend(api_files)
    else:
        # Try localhost first (most common for local dev)
        for url in ["http://localhost:8188", "http://comfyui:8188"]:
            print(f"\n  Trying ComfyUI API: {url}")
            api_files = scan_comfyui_api(url)
            if api_files:
                print(f"    Found {len(api_files)} file(s) in history")
                all_files.extend(api_files)
                break
            # If localhost didn't connect, don't bother with docker hostname
            if url == "http://localhost:8188" and not api_files:
                # Check if it was just no history vs connection refused
                try:
                    import urllib.request
                    urllib.request.urlopen(f"{url}/system_stats", timeout=2)
                    print("    ComfyUI is running but has no history yet")
                    break  # No need to try docker hostname
                except Exception:
                    pass  # truly not running, try next

    # 4. Query HomePilot backend API for project files
    backend_url = args.backend_url or os.environ.get("BACKEND_URL")
    if not backend_url:
        # Auto-detect: try localhost:8000
        try:
            import urllib.request
            urllib.request.urlopen("http://localhost:8000/health", timeout=2)
            backend_url = "http://localhost:8000"
        except Exception:
            pass

    if backend_url:
        print(f"\n  HomePilot API: {backend_url}")
        if args.session:
            print(f"    Session: {args.session[:12]}...")
        backend_files = scan_backend_api(backend_url, session_token=args.session)
        if backend_files:
            print(f"    Found {len(backend_files)} media file(s) in projects")
            all_files.extend(backend_files)
        else:
            print("    No media files in projects")
    else:
        print("\n  HomePilot API: not running (skipped)")

    # Deduplicate by path
    seen_paths = set()
    unique_files = []
    for f in all_files:
        if f["path"] not in seen_paths:
            seen_paths.add(f["path"])
            unique_files.append(f)
    all_files = unique_files

    print()
    print(f"  Total unique files: {len(all_files)}")
    print()

    if args.scan_only:
        print("-" * 65)
        for f in sorted(all_files, key=lambda x: x["name"]):
            size_str = f"{f['size'] / 1024:.1f}KB" if f['size'] > 0 else "??KB"
            print(f"  [{f['type']:5s}] {f['name']:40s} {size_str:>10s}  ({f['source']})")
        print("-" * 65)
        print(f"  {len(all_files)} file(s) total")
        return

    # Generate HTML and start server
    html = generate_html(all_files)

    FileManagerHandler.html_content = html
    FileManagerHandler.all_files = all_files

    server = HTTPServer(("0.0.0.0", args.port), FileManagerHandler)
    print("=" * 65)
    print(f"  File Manager running at: http://localhost:{args.port}")
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
