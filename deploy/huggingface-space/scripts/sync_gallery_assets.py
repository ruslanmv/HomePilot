#!/usr/bin/env python3
"""
Sync HomePilot community persona thumbnails from the upstream gallery.

The Cloudflare Worker gallery — the same source the public web gallery at
https://ruslanmv.com/HomePilot/gallery.html uses — is the source of truth for
persona preview images. The Hugging Face Space, however, cannot reach that
Worker at runtime, so at runtime it serves the copies bundled in
``community/sample/``. This tool refreshes those bundled thumbnails from the
Worker so the offline app mirrors the web gallery exactly.

It is meant to run at build/deploy time (wired into ``deploy-hf.sh``) against
the staged bundle, and can also be run against the repo working tree to commit
a refreshed baseline.

Design (industry best practices for an asset mirror):
  * Idempotent — a file is only rewritten when its bytes actually change, so
    re-running is a no-op and diffs stay minimal.
  * Validated — every download is verified to be a real WEBP image before it
    is allowed to replace a bundled asset.
  * Atomic    — writes go to a temp file then os.replace(), so an interrupted
    or partial download can never corrupt an existing thumbnail.
  * Resilient — a per-persona failure is logged and skipped; if the whole
    upstream registry is unreachable the tool exits 0 (non-fatal) and leaves
    the committed fallback in place, so a transient outage never breaks a
    deploy. Pass ``--strict`` to turn any failure into a non-zero exit.
  * Pinned    — the source URL defaults to the same value the backend uses
    (``COMMUNITY_GALLERY_URL`` or the production Worker), so the app and this
    mirror can never drift onto different upstreams.

Network I/O goes through ``curl`` so the tool works identically behind an
egress proxy (CI, sandboxes) and on a direct connection.

Usage:
    sync_gallery_assets.py [SAMPLE_DIR] [--gallery-url URL] [--strict]

    SAMPLE_DIR   directory holding registry.json + persona subdirs.
                 Defaults to <repo>/community/sample.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Same default as backend/app/config.py — keep the app and this mirror pinned
# to one upstream so they can never diverge.
DEFAULT_GALLERY_URL = "https://homepilot-persona-gallery.cloud-data.workers.dev"
HTTP_TIMEOUT = 20  # seconds per request
MAX_RETRIES = 3


def log(msg: str) -> None:
    print(f"[gallery-sync] {msg}", flush=True)


def curl_get(url: str, timeout: int = HTTP_TIMEOUT, retries: int = MAX_RETRIES) -> bytes:
    """Fetch a URL with curl, following redirects, with exponential backoff."""
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            proc = subprocess.run(
                ["curl", "-fsSL", "--max-time", str(timeout), url],
                capture_output=True,
            )
            if proc.returncode == 0:
                return proc.stdout
            last = RuntimeError(
                f"curl exit {proc.returncode}: "
                f"{proc.stderr.decode('utf-8', 'ignore').strip()[:200]}"
            )
        except Exception as exc:  # pragma: no cover - defensive
            last = exc
        if attempt < retries:
            time.sleep(2 ** attempt)
    assert last is not None
    raise last


def is_webp(data: bytes) -> bool:
    """True if the bytes are a RIFF/WEBP image (magic-byte validation)."""
    return len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP"


def atomic_write(path: Path, data: bytes) -> None:
    """Write bytes to path atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def build_id_dir_map(sample_dir: Path, registry: dict) -> dict[str, str]:
    """Map persona id -> sample subdir, using the same rule as the backend.

    A registry item belongs to a sample subdir when its id starts with the
    subdir name (e.g. ``david_news_anchor`` -> ``david``). Only subdirs that
    carry a manifest.json are considered real persona samples.
    """
    dirs = [
        p.name
        for p in sorted(sample_dir.iterdir())
        if p.is_dir() and (p / "manifest.json").exists()
    ]
    mapping: dict[str, str] = {}
    for item in registry.get("items", []):
        pid = item.get("id", "")
        for dirname in dirs:
            if pid.startswith(dirname):
                mapping[pid] = dirname
                break
    return mapping


def versions_by_id(registry: dict) -> dict[str, str]:
    return {
        it.get("id", ""): (it.get("latest", {}) or {}).get("version", "1.0.0")
        for it in registry.get("items", [])
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample_dir", nargs="?", default=None)
    parser.add_argument(
        "--gallery-url",
        default=os.getenv("COMMUNITY_GALLERY_URL", DEFAULT_GALLERY_URL),
        help="Upstream gallery base URL (default: COMMUNITY_GALLERY_URL or the Worker).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if the registry or any thumbnail fails to sync.",
    )
    args = parser.parse_args()

    gallery = (args.gallery_url or "").strip().rstrip("/")
    if not gallery:
        log("no gallery URL configured (COMMUNITY_GALLERY_URL empty); nothing to sync")
        return 0

    if args.sample_dir:
        sample_dir = Path(args.sample_dir).resolve()
    else:
        sample_dir = Path(__file__).resolve().parents[3] / "community" / "sample"

    local_registry_path = sample_dir / "registry.json"
    if not local_registry_path.is_file():
        log(f"local registry not found at {local_registry_path}; nothing to sync")
        return 2 if args.strict else 0

    local_registry = json.loads(local_registry_path.read_text())

    # Fetch the upstream registry (authoritative persona list + versions).
    try:
        upstream = json.loads(curl_get(f"{gallery}/registry.json"))
    except Exception as exc:
        log(f"WARN: could not fetch upstream registry from {gallery}: {exc}")
        log("keeping bundled thumbnails as-is (offline fallback)")
        return 3 if args.strict else 0

    id_dir = build_id_dir_map(sample_dir, local_registry)
    up_ver = versions_by_id(upstream)
    loc_ver = versions_by_id(local_registry)

    synced = unchanged = failed = 0
    for pid, dirname in sorted(id_dir.items()):
        version = up_ver.get(pid) or loc_ver.get(pid, "1.0.0")
        dest = sample_dir / dirname / "assets" / f"thumb_avatar_{dirname}.webp"
        url = f"{gallery}/v/{pid}/{version}"
        try:
            data = curl_get(url)
        except Exception as exc:
            log(f"FAIL {pid}: fetch {url}: {exc}")
            failed += 1
            continue
        if not is_webp(data):
            log(f"FAIL {pid}: upstream preview is not a WEBP image ({len(data)}B) at {url}")
            failed += 1
            continue
        new_hash = hashlib.sha256(data).hexdigest()
        old_hash = (
            hashlib.sha256(dest.read_bytes()).hexdigest() if dest.is_file() else ""
        )
        if new_hash == old_hash:
            unchanged += 1
            continue
        atomic_write(dest, data)
        synced += 1
        log(f"updated {dirname} <- {pid}@{version} ({len(data)} bytes)")

    log(
        f"done: updated={synced} unchanged={unchanged} failed={failed} "
        f"(personas={len(id_dir)}, source={gallery})"
    )
    if args.strict and failed:
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
