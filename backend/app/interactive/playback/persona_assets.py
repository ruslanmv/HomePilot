"""
Persona asset resolver for Persona Live Play scene edits.

Given a persona project id, finds the canonical portrait the
playback renderer should use as the source image for every edit.
That portrait is the visual anchor for the session — every scene
is an img2img / inpaint / outpaint of it, not a fresh txt2img, so
the face stays identical across turns.

Only the currently-selected portrait is resolved in this batch.
Identity embeddings (InstantID / PhotoMaker) and pre-computed
face / outfit / background masks can layer on later — the shape
of the returned dataclass leaves room for them.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PersonaAssets:
    """What the renderer needs to run an edit on a persona.

    ``portrait_url`` is the public /files URL the frontend version
    history uses. ``portrait_path`` is the absolute filesystem path
    ComfyUI needs to load the image. ``character_prompt`` and
    ``outfit_prompt`` are stylistic anchors the recipe may inject
    into the positive prompt for continuity.
    """

    persona_project_id: str
    portrait_url: str
    portrait_path: str
    character_prompt: str = ""
    outfit_prompt: str = ""


def resolve_persona_assets(persona_project_id: str) -> Optional[PersonaAssets]:
    """Resolve a persona project's current portrait + style anchors.

    Returns ``None`` when the project can't be found, isn't a
    persona project, or has no committed portrait yet. Callers
    treat that as "no edit recipe applies" — the renderer falls
    back to the existing txt2img path so Persona Live Play still
    works in degraded mode.
    """
    pid = (persona_project_id or "").strip()
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
    """Prefer the committed ``selected_filename`` (the latest
    operator-approved portrait); fall back to scanning the sets for
    the image flagged as ``default``. Either way returns a relative
    ``/files/...`` URL."""
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
                return url if url.startswith("/") else "/" + url
    # No match — fall back to the first image in the first set.
    for s in (pap.get("sets") or []):
        if not isinstance(s, dict):
            continue
        for img in (s.get("images") or []):
            url = str((img or {}).get("url") or "").strip()
            if url:
                return url if url.startswith("/") else "/" + url
    return ""


def _ensure_files_prefix(filename_or_url: str) -> str:
    """Accepts either ``foo.png`` or ``/files/foo.png`` and returns
    the latter shape so downstream URL building is uniform."""
    if filename_or_url.startswith("/"):
        return filename_or_url
    if filename_or_url.startswith("http://") or filename_or_url.startswith("https://"):
        return filename_or_url
    return f"/files/{filename_or_url}"


def _abs_url(rel_url: str) -> str:
    if rel_url.startswith("http://") or rel_url.startswith("https://"):
        return rel_url
    base = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
    if not base:
        return rel_url
    return f"{base}{rel_url if rel_url.startswith('/') else '/' + rel_url}"


def _resolve_local_path(rel_url: str) -> str:
    """Map a ``/files/...`` URL back to the absolute path on disk.

    ComfyUI's LoadImage node needs a filesystem path, so we can't
    just hand it a URL. The ``UPLOAD_DIR`` env + ``DATA_DIR``
    default mirror the convention in ``app.files`` and elsewhere
    in the backend. Returns ``""`` when the file isn't on disk so
    the caller gracefully falls back to txt2img.
    """
    if not rel_url:
        return ""
    # Absolute URLs can't be mapped — live-play needs a local file.
    if rel_url.startswith("http://") or rel_url.startswith("https://"):
        return ""
    # Strip the /files/ prefix.
    path_tail = rel_url
    if path_tail.startswith("/files/"):
        path_tail = path_tail[len("/files/"):]
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


def load_assets(persona_id: str) -> Dict[str, str]:
    """Legacy/simple path contract for persona_live action routes.

    Returns stable keys even if some files are missing, so callers
    can deterministically construct recipe inputs.
    """
    resolved = resolve_persona_assets(persona_id)
    base = f"persona_assets/{persona_id}"
    portrait = resolved.portrait_path if resolved else f"{base}/portrait.png"
    return {
        "portrait": portrait,
        "embedding": f"{base}/instantid.pt",
        "face_mask": f"{base}/face_mask.png",
        "outfit_mask": f"{base}/outfit_mask.png",
        "bg_mask": f"{base}/bg_mask.png",
        "pose_skeleton": f"{base}/pose.json",
        "negative_prompt": "low quality, artifacts, deformed",
    }
