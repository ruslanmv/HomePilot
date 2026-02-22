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

from .config import OLLAMA_BASE_URL, TOOL_TIMEOUT_S


# ---------------------------------------------------------------------------
# Known vision model patterns — single source of truth
# ---------------------------------------------------------------------------

VISION_MODEL_PATTERNS: List[str] = [
    "moondream", "llava", "gemma3", "minicpm-v", "llama3.2-vision",
    "qwen3-vl", "qwen2-vl", "internvl", "smolvlm", "bakllava",
]
"""
Substrings to match against Ollama model names to identify vision-capable models.
Imported by main.py for /models filtering, /health/detailed, and /v1/multimodal/status.
Add new vision model families here — they will automatically appear everywhere.
"""


# ---------------------------------------------------------------------------
# Intent detection — lightweight keyword matching
# ---------------------------------------------------------------------------

_VISION_INTENT_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bread\s+(this|the|my)\s+(image|picture|photo|screenshot|screen|pic)\b",
        r"\bdescribe\s+(this|the|my)\s+(image|picture|photo|screenshot|screen|pic)\b",
        r"\bwhat('?s| is)\s+in\s+(this|the|my)\s+(image|picture|photo|screenshot|screen|pic)\b",
        r"\banalyze\s+(this|the|my)\s+(image|picture|photo|screenshot|screen|pic)\b",
        r"\bocr\s+(this|the|my)\b",
        r"\btranscribe\s+(this|the|my)\b",
        r"\bextract\s+text\b",
        r"\blook\s+at\s+(this|the|my)\s+(image|picture|photo|screenshot|screen|pic)\b",
        r"\bwhat\s+does?\s+(this|the|my)\s+(image|picture|photo|screenshot)\s+(show|contain|say)\b",
        r"\bcan\s+you\s+see\b",
        r"\btell\s+me\s+(about|what)\s+(this|the|my)\s+(image|picture|photo)\b",
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
    """
    parsed = urlparse(image_url)
    path = parsed.path

    # Match /files/<filename> (from path or full URL)
    if path.startswith("/files/"):
        filename = path[len("/files/"):]
        candidate = upload_path / filename
        if candidate.exists() and candidate.is_file():
            return candidate

    # Also try matching the raw URL if it contains /files/
    if "/files/" in image_url:
        idx = image_url.index("/files/")
        filename = image_url[idx + len("/files/"):]
        # Strip query params if present
        if "?" in filename:
            filename = filename[:filename.index("?")]
        candidate = upload_path / filename
        if candidate.exists() and candidate.is_file():
            return candidate

    return None


async def _load_image_bytes(image_url: str, upload_path: Path) -> tuple[bytes, str]:
    """
    Load image bytes from a local path or remote URL.
    Returns (raw_bytes, mime_type).
    """
    # Try local resolution first
    local_path = _resolve_local_image(image_url, upload_path)
    if local_path:
        raw = local_path.read_bytes()
        suffix = local_path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }
        mime = mime_map.get(suffix, "image/png")
        return raw, mime

    # Remote fetch
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


async def _detect_first_vision_model(base_url: str) -> Optional[str]:
    """
    Query Ollama for installed models and return the first that matches
    a known vision pattern. Returns None if Ollama is unreachable or no
    vision model is installed.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base_url}/api/tags")
            if r.status_code != 200:
                return None
            data = r.json()
            for m in data.get("models", []):
                name = m.get("name", "")
                if is_vision_model(name):
                    return name
    except Exception:
        pass
    return None


async def analyze_image_ollama(
    image_url: str,
    upload_path: Path,
    *,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    user_prompt: Optional[str] = None,
    nsfw_mode: bool = False,
    mode: str = "both",  # caption | ocr | both
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
        mdl = await _detect_first_vision_model(base)

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

    # Load and encode image
    raw_bytes, mime_type = await _load_image_bytes(image_url, upload_path)
    img_b64 = _image_to_base64(raw_bytes)

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

    # Ollama vision API: /api/chat with images array
    payload = {
        "model": mdl,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": prompt,
                "images": [img_b64],
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
                fallback = await _detect_first_vision_model(base)
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

    return {
        "ok": True,
        "analysis_text": content,
        "meta": {
            "model": mdl,
            "mode": mode,
            "image_size_bytes": len(raw_bytes),
            "mime_type": mime_type,
        },
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
) -> Dict[str, Any]:
    """
    Top-level dispatcher for multimodal image analysis.
    Currently supports Ollama; extensible to other providers.
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
        )

    return {
        "ok": False,
        "error": f"Multimodal provider '{provider}' is not supported. Use 'ollama'.",
        "analysis_text": "",
        "meta": {"provider": provider, "model": model, "mode": mode},
    }
