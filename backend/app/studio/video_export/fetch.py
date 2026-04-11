from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx


def infer_extension_from_url(url: str, fallback: str = ".bin") -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    filename = (qs.get("filename") or [""])[0]
    if filename:
        ext = Path(filename).suffix
        if ext:
            return ext.lower()

    ext = Path(parsed.path).suffix
    if ext:
        return ext.lower()

    mime, _ = mimetypes.guess_type(url)
    if mime:
        guessed = mimetypes.guess_extension(mime)
        if guessed:
            return guessed.lower()

    return fallback


def download_to_path(url: str, dest: Path, timeout_sec: float = 60.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    timeout = httpx.Timeout(timeout_sec, connect=min(10.0, timeout_sec))
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes():
                if chunk:
                    f.write(chunk)
    return dest


def materialize_remote_source(url: str, dest_dir: Path, stem: str) -> Path:
    ext = infer_extension_from_url(url, fallback=".dat")
    dest = dest_dir / f"{stem}{ext}"
    return download_to_path(url, dest)
