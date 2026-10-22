"""
What an upload must be before it is stored (docs/design/MEDIA_STORAGE.md, Phase 4).

- A file presented as an image (by MIME type or extension) must start like one: PNG, JPEG,
  GIF, WebP or BMP. Anything else posing as an image is refused with 400 — before any bytes
  reach storage.
- ``MEDIA_SCAN_COMMAND`` (unset by default) names a scanner, e.g. ``clamdscan --no-summary``:
  it runs on a temporary copy with the path appended, and a non-zero exit refuses the file.
  That is the quarantine: nothing is stored until the scanner has said yes.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)
HEAD_BYTES = 16


def sniff_image(head: bytes) -> Optional[str]:
    """The image type the first bytes say, or None."""
    head = bytes(head or b"")
    for magic, mime in _SIGNATURES:
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def claims_image(declared_mime: str, filename: str) -> bool:
    mime = (declared_mime or "").split(";", 1)[0].strip().lower()
    ext = Path(filename or "").suffix.lower()
    return mime.startswith("image/") or ext in IMAGE_EXTS


def check_image_claim(head: bytes, declared_mime: str, filename: str) -> None:
    """400 when the file says it is an image and its bytes say it is not."""
    if claims_image(declared_mime, filename) and sniff_image(head) is None:
        raise HTTPException(
            status_code=400,
            detail=f"{filename or 'The file'} is not the image it claims to be; PNG, JPEG, GIF, WebP and BMP are accepted.",
        )


def scan_command() -> list:
    raw = (os.getenv("MEDIA_SCAN_COMMAND") or "").strip()
    return shlex.split(raw) if raw else []


def scan_bytes(data: bytes, filename: str = "") -> None:
    """Run the configured scanner on a temporary copy; 400 when it objects. No-op when none is set."""
    command = scan_command()
    if not command:
        return
    suffix = Path(filename or "").suffix[:16]
    with tempfile.NamedTemporaryFile(prefix="hp-scan-", suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        result = subprocess.run(command + [path], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        os.unlink(path)
        raise HTTPException(status_code=503, detail=f"The upload scanner could not run: {e}") from e
    os.unlink(path)
    if result.returncode != 0:
        print(f"[MEDIA] scanner refused {filename!r}: exit {result.returncode} {result.stdout.strip()[:200]}")
        raise HTTPException(status_code=400, detail=f"{filename or 'The file'} was refused by the upload scanner.")
