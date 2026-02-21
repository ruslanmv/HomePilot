# backend/app/personas/avatar_assets.py
"""
Durable avatar storage for persona projects.

When a user selects an avatar (from ComfyUI generation or upload), this module:
1. Copies the image into the project's owned storage folder
2. Generates a top-crop thumbnail (face zone anchored)
3. Returns relative paths that /files can serve consistently

This ensures avatars survive across host changes, Docker port changes,
and cleanup of temporary ComfyUI outputs.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class AvatarCommitResult:
    """Result of committing an avatar into project-owned storage."""
    selected_filename: str
    thumb_filename: str


def _safe_basename(name: str) -> str:
    """Prevent path traversal — keep only the final component."""
    base = os.path.basename(name)
    if base in ("", ".", ".."):
        raise ValueError("Invalid filename")
    # Reject if original input contained directory separators (traversal attempt)
    if name != base:
        raise ValueError("Invalid filename")
    return base


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _top_crop_thumb(src_path: Path, dst_path: Path, size: int = 256) -> None:
    """
    Create a square thumbnail anchored to the top (face zone),
    then resize to ``size x size``.
    WebP output is compact and great for UI thumbnails.
    """
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        side = min(w, h)
        left = (w - side) // 2
        top = 0  # anchor to top for face visibility
        box = (left, top, left + side, top + side)
        cropped = im.crop(box)
        thumb = cropped.resize((size, size), Image.LANCZOS)
        thumb.save(dst_path, format="WEBP", quality=85, method=6)


def commit_persona_avatar(
    upload_root: Path,
    project_root: Path,
    source_filename: str,
) -> AvatarCommitResult:
    """
    Copy a generated/uploaded image into the persona project's owned storage.

    Source: ``upload_root / <source_filename>``
    Destination: ``project_root / persona / appearance / avatar_<stem>.<ext>``
    Thumbnail: ``project_root / persona / appearance / thumb_avatar_<stem>.webp``

    Returns paths relative to ``upload_root`` so ``/files/<path>`` serves them.
    """
    src_base = _safe_basename(source_filename)
    src_path = upload_root / src_base
    if not src_path.exists():
        raise FileNotFoundError(f"Source image not found: {src_base}")

    appearance_dir = project_root / "persona" / "appearance"
    _ensure_dir(appearance_dir)

    # Preserve original extension
    ext = src_path.suffix.lower() or ".png"
    avatar_name = f"avatar_{src_path.stem}{ext}"
    avatar_path = appearance_dir / avatar_name

    # Copy into project-owned storage
    shutil.copy2(src_path, avatar_path)

    # Create thumbnail
    thumb_name = f"thumb_avatar_{src_path.stem}.webp"
    thumb_path = appearance_dir / thumb_name
    _top_crop_thumb(avatar_path, thumb_path, size=256)

    # Return relative-to-upload-root paths so /files can serve them
    rel_avatar = str(avatar_path.relative_to(upload_root))
    rel_thumb = str(thumb_path.relative_to(upload_root))
    return AvatarCommitResult(selected_filename=rel_avatar, thumb_filename=rel_thumb)


def commit_persona_image(
    upload_root: Path,
    project_root: Path,
    source_filename: str,
    prefix: str = "img",
) -> str:
    """
    Copy a single generated image into the persona project's appearance folder.

    Unlike ``commit_persona_avatar`` this does **not** generate a thumbnail —
    it is used for batch siblings and outfit images that live alongside the
    main avatar.

    Returns the path relative to ``upload_root`` so ``/files/<path>`` serves it.
    """
    src_base = _safe_basename(source_filename)
    src_path = upload_root / src_base
    if not src_path.exists():
        raise FileNotFoundError(f"Source image not found: {src_base}")

    appearance_dir = project_root / "persona" / "appearance"
    _ensure_dir(appearance_dir)

    ext = src_path.suffix.lower() or ".png"
    dest_name = f"{prefix}_{src_path.stem}{ext}"
    dest_path = appearance_dir / dest_name

    shutil.copy2(src_path, dest_path)

    return str(dest_path.relative_to(upload_root))
