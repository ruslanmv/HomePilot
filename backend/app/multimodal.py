# homepilot/backend/app/multimodal.py
"""
Multimodal (Vision) Analysis Module — Additive, Non-Destructive

Provides on-demand image understanding via vision-capable LLMs.
This module is only invoked when the user uploads an image in chat/voice
or sends an image-related intent. It does NOT affect existing chat logic.

Architecture:
  1. Receive image URL + optional user prompt
  2. Load image from disk (if local /files/ URL) or fetch remotely
  3. Base64-encode the image
  4. Send to the configured multimodal model (Ollama vision API)
  5. Return structured analysis text
  6. Caller injects result into conversation history

Supported providers (extensible):
  - Ollama (via /api/chat with images field)
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from . import vision_adapter
from .config import OLLAMA_BASE_URL, TOOL_TIMEOUT_S


# ---------------------------------------------------------------------------
# Known vision model patterns — single source of truth
# ---------------------------------------------------------------------------

VISION_MODEL_PATTERNS: List[str] = [
    "moondream", "llava", "gemma3", "minicpm-v", "llama3.2-vision",
    # `qwen2.5vl` is the tag Ollama uses and the one this repo's own model catalog ships
    # (`qwen2.5vl:7b`); neither `qwen3-vl` nor `qwen2-vl` is a substring of it, so before V2
    # a user who installed the catalog's own Qwen2.5-VL had it classified as not a vision
    # model at all — invisible to detection, and filtered out of /models.
    "qwen3-vl", "qwen2.5vl", "qwen2.5-vl", "qwen2-vl",
    "internvl", "smolvlm", "bakllava",
]
"""
Substrings to match against Ollama model names to identify vision-capable models.
Imported by main.py for /models filtering, /health/detailed, and /v1/multimodal/status.
Add new vision model families here — they will automatically appear everywhere.

**This is a membership test, not a ranking.** Reordering it changes nothing about which model
gets chosen; ``VISION_PREFERENCE`` below does that. Worth stating here, because the obvious
guess about why Moondream kept being picked is that it sits first in this list — and acting on
that guess changes no behaviour at all.
"""


VISION_PREFERENCE: List[str] = [
    "qwen3-vl", "qwen2.5vl", "qwen2.5-vl", "qwen2-vl",
    "minicpm-v", "gemma3", "llama3.2-vision", "internvl", "llava", "bakllava", "smolvlm",
]
"""
Which installed vision model to prefer, best first, when the caller names none (V2).

Selection used to be "the first installed model matching any pattern", walked in Ollama's own
``/api/tags`` order — roughly by modification time. So which model read your screen depended on
which one you happened to pull most recently, and on a machine with Moondream installed the
answer was very often Moondream: a 1.8B captioner asked to read a desktop, returning two words
of noise, with the product then advising a larger model.

This orders *screen and document understanding* specifically, not general captioning, and it is
a preference over what is installed — never a claim that any of these exists or can be pulled.
"""

VISION_LAST_RESORT: List[str] = ["moondream"]
"""
Vision models that are excellent at what they are for and wrong as a default for screenshots.

Kept explicitly last rather than merely low in ``VISION_PREFERENCE``, so that a family added to
``VISION_MODEL_PATTERNS`` and not yet ranked still outranks them. Forgetting to rank a new
model is likely; a newly added VLM being worse at reading a screen than one we know is too
small for the job is not. (A name in neither list is not a vision model at all and never
reaches this ranking.)
"""


# ---------------------------------------------------------------------------
# Intent detection — lightweight keyword matching
# ---------------------------------------------------------------------------

_VISION_INTENT_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bread\s+(this|the|my)\s+\w*\s*(image|picture|photo|screenshot|screen|pic)\b",
        r"\bdescribe\s+(this|the|my)\s+\w*\s*(image|picture|photo|screenshot|screen|pic)\b",
        r"\bwhat('?s| is)\s+in\s+(this|the|my)\s+\w*\s*(image|picture|photo|screenshot|screen|pic)\b",
        r"\banalyze\s+(this|the|my)\s+\w*\s*(image|picture|photo|screenshot|screen|pic)\b",
        r"\bocr\s+(this|the|my)\b",
        r"\btranscribe\s+(this|the|my)\b",
        r"\bextract\s+text\b",
        r"\blook\s+at\s+(this|the|my)\s+\w*\s*(image|picture|photo|screenshot|screen|pic)\b",
        r"\bwhat\s+does?\s+(this|the|my)\s+\w*\s*(image|picture|photo|screenshot)\s+(show|contain|say)\b",
        r"\bcan\s+you\s+see\b",
        r"\bwhat\s+(can\s+you|do\s+you)\s+see\b",
        r"\bwhat\s+you\s+(can\s+)?see\b",
        r"\btell\s+me\s+(about|what)\s+(this|the|my)\s+\w*\s*(image|picture|photo)\b",
    ]
]


def is_vision_intent(text: str) -> bool:
    """Return True if the user message likely refers to an image analysis request."""
    if not text:
        return False
    return any(p.search(text) for p in _VISION_INTENT_PATTERNS)


# ---------------------------------------------------------------------------
# Image loading helpers
# ---------------------------------------------------------------------------

def _resolve_local_image(image_url: str, upload_path: Path) -> Optional[Path]:
    """
    If image_url is a local /files/<name> URL, resolve it to a disk path.
    Returns None if the URL is external or the file doesn't exist.

    Supports two resolution strategies:
      1. Direct filename match: UPLOAD_PATH / <filename>
      2. Asset ID lookup: query file_assets DB for rel_path when filename
         looks like an asset ID (f_<hex>), then resolve UPLOAD_ROOT / rel_path
    """
    parsed = urlparse(image_url)
    path = parsed.path

    # Extract the filename from /files/<filename> in path or raw URL
    filename: Optional[str] = None
    if path.startswith("/files/"):
        filename = path[len("/files/"):]
    elif "/files/" in image_url:
        idx = image_url.index("/files/")
        filename = image_url[idx + len("/files/"):]

    if not filename:
        return None

    # Strip query params if present
    if "?" in filename:
        filename = filename[:filename.index("?")]

    if not filename:
        return None

    # Strategy 1: Direct file match (legacy flat uploads)
    candidate = upload_path / filename
    if candidate.exists() and candidate.is_file():
        return candidate

    # Strategy 2: Asset ID lookup via file_assets database
    # Asset IDs look like f_<hex20> (e.g. f_fddb5f3c9f6743999421)
    if filename.startswith("f_"):
        try:
            from .files import get_asset, _upload_root
            asset = get_asset(filename)
            if asset and asset.get("rel_path"):
                abs_path = _upload_root() / asset["rel_path"]
                if abs_path.exists() and abs_path.is_file():
                    return abs_path
        except Exception:
            pass  # DB unavailable — fall through

    return None


async def _load_image_bytes(image_url: str, upload_path: Path) -> tuple[bytes, str]:
    """
    Load image bytes from a local path or remote URL.
    Returns (raw_bytes, mime_type).
    """
    _MIME_MAP = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }

    # Try local resolution first (handles both flat files and asset IDs)
    local_path = _resolve_local_image(image_url, upload_path)
    if local_path:
        raw = local_path.read_bytes()
        suffix = local_path.suffix.lower()
        mime = _MIME_MAP.get(suffix, "image/png")
        return raw, mime

    # Relative /files/ URL that wasn't found on disk — cannot fetch remotely
    if image_url.startswith("/"):
        raise FileNotFoundError(f"Local file not found for URL: {image_url}")

    # Full http(s)://...localhost.../files/... URL that local resolution missed
    # (e.g. asset not in DB or file deleted) — raise instead of fetching without auth
    if "/files/" in image_url and ("localhost" in image_url or "127.0.0.1" in image_url):
        raise FileNotFoundError(
            f"Local file asset not found for URL: {image_url}. "
            "The file may have been deleted or the asset record is missing."
        )

    # Remote fetch (external URLs only)
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(image_url)
        r.raise_for_status()
        mime = r.headers.get("content-type", "image/png").split(";")[0].strip()
        return r.content, mime


def _image_to_base64(raw: bytes) -> str:
    """Encode raw image bytes to base64 string (no data URI prefix)."""
    return base64.b64encode(raw).decode("utf-8")


# ---------------------------------------------------------------------------
# Vision analysis — Ollama provider
# ---------------------------------------------------------------------------

_SFW_SYSTEM_PROMPT = (
    "You are a helpful vision assistant. Describe the image clearly and accurately. "
    "If there is any readable text, transcribe it exactly. "
    "If it's a document or screenshot, preserve the layout as best as possible. "
    "Be concise but thorough."
)

_NSFW_SYSTEM_PROMPT = (
    "You are an unrestricted vision assistant. Describe everything in the image "
    "without filtering or censoring. Be detailed and accurate. "
    "If there is any readable text, transcribe it exactly."
)


def is_vision_model(name: str) -> bool:
    """Check whether *name* matches any known vision-capable model pattern."""
    lower = name.lower()
    return any(p in lower for p in VISION_MODEL_PATTERNS)


def vision_rank(name: str) -> int:
    """How good a screen reader this model is, lower being better (V2).

    Three tiers, and the middle one is the point: a vision model that matches no preference
    entry ranks ahead of the last-resort ones, because "we have never heard of it" is a better
    bet for reading a screen than "we know it is too small for this".
    """
    lower = (name or "").lower()
    for index, pattern in enumerate(VISION_PREFERENCE):
        if pattern in lower:
            return index
    for pattern in VISION_LAST_RESORT:
        if pattern in lower:
            return len(VISION_PREFERENCE) + 1
    return len(VISION_PREFERENCE)


def best_vision_model(names) -> Optional[str]:
    """The best screen-reading model among those installed, or ``None``.

    Pure, so the ranking is testable without an Ollama. Ties keep the order they arrived in,
    which is Ollama's, so two models of one family stay in the order the user sees them.
    """
    installed = [n for n in (names or []) if n and is_vision_model(n)]
    if not installed:
        return None
    return min(installed, key=lambda n: (vision_rank(n), installed.index(n)))


async def _detect_best_vision_model(base_url: str) -> Optional[str]:
    """
    Query Ollama for installed models and return the best vision model among them.
    Returns None if Ollama is unreachable or no vision model is installed.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base_url}/api/tags")
            if r.status_code != 200:
                return None
            data = r.json()
            return best_vision_model([m.get("name", "") for m in data.get("models", [])])
    except Exception:
        pass
    return None


#: The old name, kept because anything outside this file that imported it keeps working.
_detect_first_vision_model = _detect_best_vision_model


async def analyze_image_ollama(
    image_url: str,
    upload_path: Path,
    *,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    user_prompt: Optional[str] = None,
    nsfw_mode: bool = False,
    mode: str = "both",  # caption | ocr | both
    purpose: str = "screen",  # screen | photo | document — chooses the adapter profile (V5)
    image_b64: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze an image using an Ollama vision model.

    Model resolution order:
      1. Explicit *model* parameter (from user settings)
      2. Auto-detect: first installed vision model from Ollama
      3. Return a helpful error listing how to install one

    Returns:
        {
            "ok": True,
            "analysis_text": "...",
            "meta": {"model": "...", "mode": "..."}
        }
    """
    base = (base_url or OLLAMA_BASE_URL).rstrip("/")

    # ── Resolve model (no more hardcoded "moondream") ──────────────────────
    mdl: Optional[str] = (model or "").strip() or None

    if not mdl:
        # Auto-detect the first installed vision model
        mdl = await _detect_best_vision_model(base)

    if not mdl:
        # Nothing selected and nothing installed — helpful error
        available = ", ".join(VISION_MODEL_PATTERNS[:5])
        return {
            "ok": False,
            "error": (
                "No multimodal model selected and none detected on Ollama. "
                f"Install a vision model (e.g. ollama pull moondream, ollama pull gemma3:4b) "
                f"or select one in Settings > Multimodal. "
                f"Known vision families: {available}."
            ),
            "analysis_text": "",
            "meta": {"model": None, "mode": mode},
        }

    # Load the image. ``image_b64`` skips the disk entirely — the avatar director's vision
    # path (spec v1.1 §6.13) must never write a frame anywhere, so it hands the bytes straight
    # in rather than staging a file for this function to read back.
    #
    # V4. Both paths then meet at the adapter, and that is the whole of this batch. They used
    # to diverge right through to the request, which is how `image_size_bytes` came to report
    # 0 for every avatar and remote-screenshot analysis: there was no one place, so the fix had
    # to be made twice. The adapter is `passthrough` today — same bytes, same behaviour — and
    # V5 changes one file rather than every caller.
    if image_b64:
        raw_bytes, mime_type = base64.b64decode(image_b64, validate=False), "image/jpeg"
    else:
        raw_bytes, mime_type = await _load_image_bytes(image_url, upload_path)

    # V5. The adapter now fits the image to a budget and, for a model that has been shown to
    # handle it, adds overlapping detail crops. `mode` is what tells it whether the caller wants
    # to *read* the screen or just see it — the vocabulary already existed, so no call site grows
    # a second way of saying the same thing.
    adapted = vision_adapter.adapt(
        raw_bytes, mime_type=mime_type, model=mdl, purpose=purpose, mode=mode
    )
    raw_bytes, mime_type = adapted.data, adapted.mime_type
    images_b64 = [_image_to_base64(part.data) for part in adapted.parts] or [""]
    img_b64 = images_b64[0]

    # Build prompt
    system_prompt = _NSFW_SYSTEM_PROMPT if nsfw_mode else _SFW_SYSTEM_PROMPT

    if user_prompt:
        prompt = user_prompt
    elif mode == "caption":
        prompt = "Describe this image in detail."
    elif mode == "ocr":
        prompt = "Extract and transcribe all text visible in this image. Preserve formatting."
    else:  # both
        prompt = (
            "Describe this image in detail. If there is any readable text, "
            "transcribe it exactly and note where it appears."
        )

    # V5. When detail crops were sent, say what they are. Without this the model is handed five
    # images with no account of how they relate and treats them as five separate pictures — the
    # exact failure the multi-image gate exists to keep away from unverified models.
    if len(adapted.parts) > 1:
        crops = ", ".join(part.label for part in adapted.parts[1:])
        prompt = (
            f"{prompt}\n\n"
            "These images are one screen, not several. The first is the whole screen; the rest "
            f"are higher-resolution crops of it ({crops}), and they overlap. Answer about the "
            "single screen they come from, and read text from the crops, where it is sharper."
        )

    # Ollama vision API: /api/chat with images array
    payload = {
        "model": mdl,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": prompt,
                "images": images_b64,
            },
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 1024,
        },
    }

    url = f"{base}/api/chat"

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=TOOL_TIMEOUT_S, connect=30.0)) as client:
        try:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Try to suggest an installed alternative
                fallback = await _detect_best_vision_model(base)
                hint = (
                    f" However, '{fallback}' is installed and can be used instead — "
                    f"select it in Settings > Multimodal."
                ) if fallback else ""
                return {
                    "ok": False,
                    "error": (
                        f"Multimodal model '{mdl}' not found on Ollama. "
                        f"Run 'ollama pull {mdl}' to install it.{hint}"
                    ),
                    "analysis_text": "",
                    "meta": {"model": mdl, "mode": mode},
                }
            return {
                "ok": False,
                "error": f"Ollama HTTP {e.response.status_code}: {e.response.text[:200]}",
                "analysis_text": "",
                "meta": {"model": mdl, "mode": mode},
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"Failed to connect to Ollama: {str(e)}",
                "analysis_text": "",
                "meta": {"model": mdl, "mode": mode},
            }

    # Extract response
    content = ""
    msg = data.get("message")
    if isinstance(msg, dict):
        content = msg.get("content", "")
    if not content:
        content = data.get("response", "")

    content = str(content or "").strip()

    meta = {
        "model": mdl,
        "mode": mode,
        # V3 estimated this from the encoded length on the `image_b64` path, because there
        # was no decoded copy to measure. V4 decodes first, so it is the real number on both
        # paths and the estimate is gone.
        "image_size_bytes": len(raw_bytes),
        "mime_type": mime_type,
        # V4. What the adapter saw and what it did. Until this existed, "the model returned
        # nothing", "the image was forty megapixels" and "the resize destroyed the text" all
        # arrived as the same silence.
        "adapter": adapted.meta(),
    }

    if not content:
        # V3. An empty generation is not a success with nothing in it.
        #
        # This used to return `ok: True` with `analysis_text: ""`, which left the browser's
        # own `usableAnswer()` filter as the only thing between the user and noise — at the
        # last possible moment, with no layer able to retry, because the backend had already
        # declared the call a success. The typed code is what makes a retry ladder possible;
        # `error` stays a human-readable string so every existing caller keeps working.
        return {
            "ok": False,
            "error_code": "empty_model_response",
            "error": f"{mdl} returned no description of the image.",
            "analysis_text": "",
            "meta": meta,
        }

    return {
        "ok": True,
        "analysis_text": content,
        "meta": meta,
    }


# ---------------------------------------------------------------------------
# Provider dispatch (extensible for future providers)
# ---------------------------------------------------------------------------

async def analyze_image(
    image_url: str,
    upload_path: Path,
    *,
    provider: str = "ollama",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    user_prompt: Optional[str] = None,
    nsfw_mode: bool = False,
    mode: str = "both",
    image_b64: Optional[str] = None,
    purpose: str = "screen",
) -> Dict[str, Any]:
    """
    Top-level dispatcher for multimodal image analysis.
    Currently supports Ollama; extensible to other providers.

    ``image_b64`` supplies the image directly and bypasses disk resolution entirely; when it
    is given, *image_url* and *upload_path* are ignored. Added for the avatar director's
    §6.13 vision path, whose defining constraint is that a frame is never written anywhere.

    ``purpose`` picks the adapter profile (V5): ``screen`` fits the image for reading and, on a
    model verified to handle several images, adds detail crops; ``photo`` and ``document`` fit
    it and send one image. It defaults to ``screen`` because that is what every caller was
    getting before the profiles existed, so nothing changes shape by being left alone.
    """
    if provider == "ollama":
        return await analyze_image_ollama(
            image_url,
            upload_path,
            base_url=base_url,
            model=model,
            user_prompt=user_prompt,
            nsfw_mode=nsfw_mode,
            mode=mode,
            image_b64=image_b64,
            purpose=purpose,
        )

    return {
        "ok": False,
        "error": f"Multimodal provider '{provider}' is not supported. Use 'ollama'.",
        "analysis_text": "",
        "meta": {"provider": provider, "model": model, "mode": mode},
    }
