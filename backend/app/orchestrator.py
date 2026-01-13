# homepilot/backend/app/orchestrator.py
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Optional, Literal

from .comfy import run_workflow
from .llm import chat as llm_chat
from .prompts import BASE_SYSTEM, FUN_SYSTEM
from .storage import add_message, get_recent
from .config import DEFAULT_PROVIDER

ProviderName = Literal["openai_compat", "ollama"]

IMAGE_RE = re.compile(r"\b(imagine|generate|create|draw|make)\b.*\b(image|picture|photo|art)\b", re.I)
EDIT_RE = re.compile(r"\b(edit|inpaint|replace|remove|change)\b", re.I)
ANIM_RE = re.compile(r"\b(animate|make (a )?video|image\s*to\s*video)\b", re.I)
URL_RE = re.compile(r"(https?://\S+)")


def _norm_mode(mode: Optional[str]) -> str:
    return (mode or "").strip().lower()


async def orchestrate(
    user_text: str,
    conversation_id: Optional[str] = None,
    fun_mode: bool = False,
    mode: Optional[str] = None,
    provider: Optional[ProviderName] = None,
) -> Dict[str, Any]:
    """
    Main router:
      - chat -> LLM (provider selectable)
      - imagine -> txt2img workflow
      - edit/animate (with URL) -> edit/img2vid workflow

    Returns stable schema:
      {"conversation_id": str, "text": str, "media": dict | None}
    """
    cid = conversation_id or str(uuid.uuid4())
    text_in = (user_text or "").strip()

    # Persist user message
    add_message(cid, "user", text_in)

    # Detect URL (for edit/animate)
    url_match = URL_RE.search(text_in)
    image_url = url_match.group(1) if url_match else ""

    m = _norm_mode(mode)

    # --- Animate ---
    if (m == "animate") or (image_url and ANIM_RE.search(text_in)):
        if not image_url:
            text = "To animate, upload an image first (or paste an image URL)."
            add_message(cid, "assistant", text)
            return {"conversation_id": cid, "text": text, "media": None}

        res = run_workflow(
            "img2vid",
            {"image_url": image_url, "motion": "subtle cinematic camera drift", "seconds": 6},
        )
        video_url = (res.get("videos") or [None])[0]
        text = "Here you go."
        add_message(cid, "assistant", text)
        return {"conversation_id": cid, "text": text, "media": {"video_url": video_url}}

    # --- Edit ---
    if (m == "edit") or (image_url and EDIT_RE.search(text_in)):
        if not image_url:
            text = "To edit, upload an image first (or paste an image URL)."
            add_message(cid, "assistant", text)
            return {"conversation_id": cid, "text": text, "media": None}

        res = run_workflow("edit", {"image_url": image_url, "instruction": text_in})
        images = res.get("images", []) or []
        text = "Done."
        add_message(cid, "assistant", text)
        return {"conversation_id": cid, "text": text, "media": {"images": images}}

    # --- Imagine ---
    if (m == "imagine") or IMAGE_RE.search(text_in):
        res = run_workflow("txt2img", {"prompt": text_in})
        images = res.get("images", []) or []
        text = "Generated a few variations."
        add_message(cid, "assistant", text)
        return {"conversation_id": cid, "text": text, "media": {"images": images}}

    # --- Normal chat ---
    history = get_recent(cid, limit=24)
    system = BASE_SYSTEM + ("\n" + FUN_SYSTEM if fun_mode else "")

    messages = [{"role": "system", "content": system}]
    for role, content in history:
        messages.append({"role": role, "content": content})

    prov: ProviderName = provider or DEFAULT_PROVIDER  # type: ignore

    try:
        out = await llm_chat(
            messages,
            provider=prov,
            temperature=(0.9 if fun_mode else 0.7),
            max_tokens=900,
        )
    except Exception as e:
        # Don't crash the API; return a stable response
        err = f"LLM error ({prov}): {str(e)}"
        add_message(cid, "assistant", err)
        return {"conversation_id": cid, "text": err, "media": None}

    # Robust parsing
    text = (
        (out.get("choices") or [{}])[0]
        .get("message", {})
        .get("content", "")
        or "…"
    )

    add_message(cid, "assistant", text)
    return {"conversation_id": cid, "text": text, "media": None}
