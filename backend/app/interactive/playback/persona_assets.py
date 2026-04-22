"""
Persona asset resolver for Persona Live Play scene edits.

Given a persona project id, finds the canonical portrait the
playback renderer should use as the source image for every edit.

Production rules in this version:
- Prefer an experience-persisted frozen portrait when provided.
- Fall back to the persona project's current canonical portrait.
- Return None when the image is not available on disk, because the
  renderer needs a real filesystem path for ComfyUI LoadImage.
- Keep the frontend/display contract separate from the renderer:
  play.py can still expose portrait URLs directly even when this
  resolver returns None.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PersonaAssets:
    """
    What the renderer needs to run an edit on a persona.

    `portrait_url` is the public URL the frontend uses.
    `portrait_path` is the absolute filesystem path ComfyUI needs.
    """

    persona_project_id: str
    portrait_url: str
    portrait_path: str
    character_prompt: str = ""
    outfit_prompt: str = ""


def resolve_persona_assets(
    persona_project_id: str,
    *,
    persisted_portrait_url: str = "",
    persisted_avatar_url: str = "",
) -> Optional[PersonaAssets]:
    """
    Resolve persona assets, preferring an experience-persisted portrait.

    Priority order:
      1. persisted_portrait_url
      2. persisted_avatar_url
      3. current canonical portrait from persona project

    Returns None when nothing usable can be resolved OR when the
    underlying image file is not present on disk.
    """
    pid = (persona_project_id or "").strip()

    frozen_url = str(persisted_portrait_url or "").strip()
    frozen_avatar = str(persisted_avatar_url or "").strip()

    # 1) Prefer frozen portrait stamped onto the experience.
    if frozen_url:
      frozen_path = _resolve_local_path(frozen_url)
      if not frozen_path:
          return None
      return PersonaAssets(
          persona_project_id=pid,
          portrait_url=_abs_url(frozen_url),
          portrait_path=frozen_path,
          character_prompt="",
          outfit_prompt="",
      )

    # 2) Fall back to frozen avatar if no portrait was saved.
    if frozen_avatar:
        frozen_path = _resolve_local_path(frozen_avatar)
        if not frozen_path:
            return None
        return PersonaAssets(
            persona_project_id=pid,
            portrait_url=_abs_url(frozen_avatar),
            portrait_path=frozen_path,
            character_prompt="",
            outfit_prompt="",
        )

    # 3) Fall back to live persona project lookup.
    if not pid:
        return None

    try:
        from ... import projects  # late import so tests can skip
    except Exception:
        return None

    try:
        project = projects.get_project_by_id(pid)
    except Exception:
        return None

    if not isinstance(project, dict):
        return None
    if project.get("project_type") != "persona":
        return None

    pap = project.get("persona_appearance") or {}
    if not isinstance(pap, dict):
        return None

    rel_url = _portrait_rel_url(pap)
    if not rel_url:
        return None

    abs_path = _resolve_local_path(rel_url)
    if not abs_path:
        return None

    avatar = pap.get("avatar_settings") or {}

    return PersonaAssets(
        persona_project_id=pid,
        portrait_url=_abs_url(rel_url),
        portrait_path=abs_path,
        character_prompt=str(avatar.get("character_prompt") or "").strip(),
        outfit_prompt=str(avatar.get("outfit_prompt") or "").strip(),
    )


# ── Helpers ─────────────────────────────────────────────────────

def _portrait_rel_url(pap: Dict[str, Any]) -> str:
    """
    Prefer the committed `selected_filename` (latest approved portrait);
    fall back to the selected image in sets; then the first available image.
    Returns a relative /files URL or an absolute URL.
    """
    committed = str(pap.get("selected_filename") or "").strip()
    if committed:
        return _ensure_files_prefix(committed)

    selected = pap.get("selected") or {}
    sel_image_id = selected.get("image_id", "")
    sel_set_id = selected.get("set_id", "")

    for s in (pap.get("sets") or []):
        if not isinstance(s, dict):
            continue
        for img in (s.get("images") or []):
            if not isinstance(img, dict):
                continue
            url = str(img.get("url") or "").strip()
            if not url:
                continue
            is_match = img.get("id") == sel_image_id and (
                img.get("set_id", s.get("set_id", "")) == sel_set_id
            )
            if is_match:
                return url if url.startswith(("http://", "https://", "/")) else f"/{url}"

    for s in (pap.get("sets") or []):
        if not isinstance(s, dict):
            continue
        for img in (s.get("images") or []):
            url = str((img or {}).get("url") or "").strip()
            if url:
                return url if url.startswith(("http://", "https://", "/")) else f"/{url}"

    return ""


def _ensure_files_prefix(filename_or_url: str) -> str:
    """
    Accepts either:
      - foo.png
      - /files/foo.png
      - /uploads/foo.png
      - https://...
    and normalizes to a URL-like string.
    """
    raw = str(filename_or_url or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw
    if raw.startswith("/"):
        return raw
    return f"/files/{raw}"


def _abs_url(rel_url: str) -> str:
    raw = str(rel_url or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw

    base = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
    if not base:
        return raw if raw.startswith("/") else f"/{raw}"
    return f"{base}{raw if raw.startswith('/') else '/' + raw}"


def _resolve_local_path(rel_url: str) -> str:
    """
    Map a /files/... or /uploads/... URL back to an absolute path on disk.

    Returns "" when the asset is not available locally.
    """
    raw = str(rel_url or "").strip()
    if not raw:
        return ""

    # Absolute URLs cannot be mapped to a local filesystem path.
    if raw.startswith(("http://", "https://")):
        return ""

    path_tail = raw
    if path_tail.startswith("/files/"):
        path_tail = path_tail[len("/files/"):]
    elif path_tail.startswith("/uploads/"):
        path_tail = path_tail[len("/uploads/"):]
    elif path_tail.startswith("/"):
        path_tail = path_tail.lstrip("/")

    upload_dir = (os.getenv("UPLOAD_DIR") or "").strip()
    if not upload_dir:
        data_dir = (os.getenv("DATA_DIR") or "").strip()
        if data_dir:
            upload_dir = os.path.join(data_dir, "uploads")

    if not upload_dir:
        return ""

    abs_path = os.path.join(upload_dir, path_tail)
    if os.path.isfile(abs_path):
        return abs_path

    log.debug("persona portrait not found on disk: %s", abs_path)
    return ""


__all__ = ["PersonaAssets", "resolve_persona_assets", "load_assets"]


def load_assets(
    persona_id: str,
    *,
    persisted_portrait_url: str = "",
    persisted_avatar_url: str = "",
) -> Dict[str, str]:
    """
    Legacy/simple path contract for persona_live action routes.

    Returns stable keys even if some files are missing, so callers
    can deterministically construct recipe inputs.
    """
    resolved = resolve_persona_assets(
        persona_id,
        persisted_portrait_url=persisted_portrait_url,
        persisted_avatar_url=persisted_avatar_url,
    )
    base = f"persona_assets/{persona_id}"
    portrait = resolved.portrait_path if resolved and resolved.portrait_path else f"{base}/portrait.png"
    return {
        "portrait": portrait,
        "embedding": f"{base}/instantid.pt",
        "face_mask": f"{base}/face_mask.png",
        "outfit_mask": f"{base}/outfit_mask.png",
        "bg_mask": f"{base}/bg_mask.png",
        "pose_skeleton": f"{base}/pose.json",
        "negative_prompt": "low quality, artifacts, deformed",
    }