"""
images.edit — edit one image with the local compute router, as a node job.

Used by the owner's own apps on the Cloud Mirror job plane or on the same
machine (e.g. SmartMirror's AI try-on: "dress this person in these clothes").
Runs ComputeRouter.edit_image, the same path HomePilot's own editing uses,
so it honours the configured provider (local ComfyUI, or OllaBridge Cloud).

Guardrails (additive, dark by default):
  - HOMEPILOT_MIRROR_IMAGE_EDIT_ENABLED (default false): when off the
    operation is not registered; the job whitelist is unchanged. The manifest
    already advertises "images.edit" when ComfyUI is ready — registering this
    handler makes that advertisement truthful without changing the manifest.
  - Input image (HP-3): an artifact id ("art_…") or base64 / data URL, capped
    by HOMEPILOT_MIRROR_RESOURCE_MAX_MB (default 10); the bytes must really be
    JPEG, PNG or WebP. HomePilot never fetches arbitrary URLs for this job.
  - The staged input is deleted when the job ends; outputs are stored as
    short-lived node artifacts (NODE_ARTIFACT_TTL_SEC).
  - Prompts and images are never logged.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("homepilot.node_ops_images_edit")

OPERATION = "images.edit"
SCOPE = "image:run"
_MIME_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_ART_ID = re.compile(r"^art_[A-Za-z0-9]{16,40}$")
_DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,(.+)$", re.S)


def enabled() -> bool:
    return os.getenv("HOMEPILOT_MIRROR_IMAGE_EDIT_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def _max_bytes() -> int:
    try:
        return max(1, int(os.getenv("HOMEPILOT_MIRROR_RESOURCE_MAX_MB", "10"))) * 1024 * 1024
    except ValueError:
        return 10 * 1024 * 1024


def sniff(data: bytes) -> Optional[str]:
    """Content type from magic bytes; only JPEG, PNG and WebP are accepted."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def resolve_input(params: Dict[str, Any]) -> Tuple[bytes, str]:
    """Return (bytes, content_type) for the job's input image or raise RESOURCE_REJECTED."""
    image = params.get("image")
    if not isinstance(image, str) or not image:
        raise ValueError("RESOURCE_REJECTED: image is required")

    if _ART_ID.match(image):
        from . import node_artifacts

        meta = node_artifacts.get_meta(image)
        path = node_artifacts.get_path(image) if meta else None
        if not path:
            raise ValueError("RESOURCE_REJECTED: artifact not found or expired")
        data = Path(path).read_bytes()
    else:
        m = _DATA_URL.match(image)
        payload = m.group(2) if m else image
        if len(payload) > (_max_bytes() * 4) // 3 + 16:
            raise ValueError("RESOURCE_REJECTED: image too large")
        try:
            data = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("RESOURCE_REJECTED: image must be an artifact id or base64") from None

    if len(data) > _max_bytes():
        raise ValueError("RESOURCE_REJECTED: image too large")
    content_type = sniff(data)
    if content_type is None:
        raise ValueError("RESOURCE_REJECTED: only JPEG, PNG or WebP images are accepted")
    return data, content_type


def _upload_dir() -> Path:
    from .config import UPLOAD_DIR

    return Path(UPLOAD_DIR)


def stage(data: bytes, content_type: str) -> Tuple[str, Path]:
    """Write the input under UPLOAD_DIR and return its /files/ reference + path."""
    rel = f"mirror-inputs/{uuid.uuid4().hex}.{_MIME_EXT[content_type]}"
    path = _upload_dir() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"/files/{rel}", path


def _local_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    allowed = {"127.0.0.1", "localhost", "::1"}
    from .config import COMFY_BASE_URL

    if COMFY_BASE_URL:
        allowed.add((urlparse(COMFY_BASE_URL).hostname or "").lower())
    return host in allowed


def _read_output(ref: str) -> Optional[bytes]:
    """Output bytes for a /files/ path or a local (ComfyUI/HomePilot) URL."""
    if ref.startswith("/files/"):
        rel = ref.replace("/files/", "", 1).split("?")[0]
        root = _upload_dir().resolve()
        path = (root / rel).resolve()
        if root in path.parents and path.is_file():
            return path.read_bytes()
        return None
    if ref.startswith(("http://", "https://")) and _local_host(ref):
        import httpx

        r = httpx.get(ref, timeout=30.0)
        return r.content if r.status_code == 200 else None
    return None


def collect_outputs(images: List[str]) -> List[Dict[str, Any]]:
    """Store generated images as short-lived node artifacts."""
    from . import node_artifacts

    artifacts: List[Dict[str, Any]] = []
    for ref in images[:4]:
        try:
            data = _read_output(ref)
        except Exception:  # noqa: BLE001 — an unreadable output is skipped, not fabricated
            data = None
        ctype = sniff(data) if data else None
        if not data or not ctype:
            continue
        meta = node_artifacts.store(data, ctype, filename=f"edit.{_MIME_EXT[ctype]}")
        artifacts.append({"artifact_id": meta.artifact_id, "content_type": ctype, "size_bytes": meta.size_bytes})
    return artifacts


async def _edit(prompt: str, image_ref: str, model: Optional[str], workflow: str) -> Any:
    from .compute.router import ComputeRouter

    return await ComputeRouter().edit_image(prompt=prompt, image=image_ref, model=model, workflow=workflow)


def op_images_edit(job: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    if not enabled():
        raise RuntimeError("CAPABILITY_UNAVAILABLE: images.edit is disabled on this node")
    prompt = params.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        raise ValueError("IMAGE_EDIT_FAILED: prompt is required (max 2000 characters)")
    workflow = params.get("workflow") or "edit"
    if not isinstance(workflow, str) or not re.match(r"^[a-z0-9_]{1,64}$", workflow):
        raise ValueError("IMAGE_EDIT_FAILED: invalid workflow")
    model = params.get("model") if isinstance(params.get("model"), str) else None

    data, content_type = resolve_input(params)
    ref, staged = stage(data, content_type)
    started = time.monotonic()
    try:
        job.set_progress(10, "edit", "editing image")
        media = asyncio.run(_edit(prompt.strip(), ref, model, workflow))
        if job.cancelled():
            return {}
        images = list(getattr(media, "images", []) or [])
        artifacts = collect_outputs(images)
        if not artifacts:
            raise RuntimeError("IMAGE_EDIT_FAILED: the edit produced no image")
        logger.info("images.edit status=ok outputs=%d ms=%d", len(artifacts),
                    int((time.monotonic() - started) * 1000))
        job.set_progress(100, "done", "")
        meta = getattr(media, "meta", {}) or {}
        return {"artifacts": artifacts, "provider": meta.get("provider", "")}
    finally:
        staged.unlink(missing_ok=True)


def register_if_enabled(register: Callable[[str, str, Callable[..., Dict[str, Any]]], None]) -> bool:
    if not enabled():
        return False
    register(OPERATION, SCOPE, op_images_edit)
    return True
