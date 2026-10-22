"""
Where ``scripts/download.py`` is.

The model installer (POST /models/install, Creator Studio bundles) runs the repo's downloader
as a subprocess. In the repo it is two levels above this package; a packaged image has no
repo around it — the Hugging Face Space copies ``backend/app`` to ``/app/app``, so the old
``parents[2] / "scripts"`` was ``/scripts/download.py`` and every install there failed with
"Download script not found", Ollama pulls included. An image ships a copy next to the
package instead (``/app/scripts/download.py``), and ``HOMEPILOT_DOWNLOAD_SCRIPT`` names any
other location.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_PACKAGE_DIR = Path(__file__).resolve().parent


def download_script(package_dir: Optional[Path] = None) -> Path:
    """The downloader's path: the configured one, else the first that exists, else the repo's."""
    configured = (os.getenv("HOMEPILOT_DOWNLOAD_SCRIPT") or "").strip()
    if configured:
        return Path(configured).expanduser()
    pkg = (package_dir or _PACKAGE_DIR).resolve()          # <repo>/backend/app, or /app/app
    candidates = [pkg.parents[1] / "scripts" / "download.py",   # <repo>/scripts
                  pkg.parent / "scripts" / "download.py"]       # /app/scripts (packaged image)
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]
