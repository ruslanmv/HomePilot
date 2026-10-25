"""Hugging Face connector — Inference Providers on the user's own account.

Linking stores the user's access token (checked against ``whoami``). From then on, Models →
provider "Hugging Face" lists the models Inference Providers actually serve, per type:

  ======== =================== ======================================================
  type     Hub pipeline tag    used by
  ======== =================== ======================================================
  chat     text-generation     ``llm.chat(provider="huggingface")`` — the router's
                               OpenAI-compatible endpoint
  vision   image-text-to-text  ``multimodal.analyze_image(provider="huggingface")``
  image    text-to-image       Imagine, when the image model is ``hf:<repo>``
  video    text-to-video       Animate, when the video model is ``hf:<repo>``
  ======== =================== ======================================================

Image and video models carry the ``hf:`` prefix because those paths pick their engine from
the model (ComfyUI checkpoints otherwise); chat and vision pick it from the provider.

Calls are billed to the linked account (its free monthly credits, or Pro). A missing or
rejected token is said plainly, never retried with someone else's.
"""
from __future__ import annotations

import asyncio
import io
import time
from typing import Any, Dict, List, Optional

from . import store
from .context import current_user_id

ID = "huggingface"
ROUTER = "https://router.huggingface.co/v1"
PREFIX = "hf:"

TASKS = {
    "chat": "text-generation",
    "multimodal": "image-text-to-text",
    "image": "text-to-image",
    "video": "text-to-video",
}

NOT_LINKED = "Connect Hugging Face in Settings → Connectors to use its models."

_cache: Dict[str, Any] = {}
_CACHE_S = 600


class NotLinked(RuntimeError):
    pass


def token(user_id: Optional[str] = None) -> str:
    return store.secret(user_id or current_user_id(), ID)


def require_token(user_id: Optional[str] = None) -> str:
    t = token(user_id)
    if not t:
        raise NotLinked(NOT_LINKED)
    return t


def strip_prefix(model: str) -> str:
    return model[len(PREFIX):] if (model or "").startswith(PREFIX) else (model or "")


# ── linking ──────────────────────────────────────────────────────────────────

async def whoami(secret: str) -> Dict[str, Any]:
    """The account behind a token, or raises ValueError with a reason a person can act on."""
    from huggingface_hub import HfApi

    try:
        info = await asyncio.to_thread(HfApi().whoami, token=secret)
    except Exception as exc:  # noqa: BLE001 — the hub raises several kinds for a bad token
        text = str(exc)
        if "401" in text or "Invalid" in text or "Unauthorized" in text:
            raise ValueError("Hugging Face did not accept this token.") from exc
        raise ValueError(f"Could not reach Hugging Face ({type(exc).__name__}).") from exc
    return info if isinstance(info, dict) else {}


# ── models ───────────────────────────────────────────────────────────────────

def _list(task: str, secret: str) -> List[Dict[str, Any]]:
    from huggingface_hub import HfApi

    models = HfApi().list_models(
        pipeline_tag=TASKS[task], inference_provider="all", sort="trending_score", limit=30,
        token=secret or None,
    )
    out = []
    for m in models:
        repo = getattr(m, "id", "") or getattr(m, "modelId", "")
        if not repo:
            continue
        out.append({
            "id": f"{PREFIX}{repo}" if task in ("image", "video") else repo,
            "name": repo,
            "likes": getattr(m, "likes", 0) or 0,
            "downloads": getattr(m, "downloads", 0) or 0,
        })
    return out


async def models(task: str) -> List[Dict[str, Any]]:
    """Models Inference Providers serve for ``task`` right now, trending first (cached 10 min)."""
    if task not in TASKS:
        raise ValueError(f"Unknown model type '{task}'. Use one of: {', '.join(TASKS)}.")
    hit = _cache.get(task)
    if hit and time.time() - hit[0] < _CACHE_S:
        return hit[1]
    listed = await asyncio.to_thread(_list, task, token())
    _cache[task] = (time.time(), listed)
    return listed


# ── chat and vision ──────────────────────────────────────────────────────────

async def chat(messages: List[Dict[str, Any]], *, model: Optional[str], temperature: float, max_tokens: int) -> Dict[str, Any]:
    from ..llm import chat_openai_compat

    return await chat_openai_compat(
        messages, temperature=temperature, max_tokens=max_tokens,
        base_url=ROUTER, model=strip_prefix(model or ""), api_key=require_token(),
    )


async def analyze_image(image_url: str, upload_path, **kwargs: Any) -> Dict[str, Any]:
    from ..multimodal import analyze_image_openai_compat

    t = token()
    if not t:
        return {"ok": False, "error": NOT_LINKED, "analysis_text": ""}
    kwargs.pop("api_key", None)
    kwargs.pop("base_url", None)
    kwargs["model"] = strip_prefix(kwargs.get("model") or "")
    return await analyze_image_openai_compat(image_url, upload_path, base_url=ROUTER, api_key=t, **kwargs)


# ── images and video, as a chat turn ─────────────────────────────────────────

_SIZES = {"1:1": (1024, 1024), "16:9": (1344, 768), "9:16": (768, 1344), "4:3": (1152, 896),
          "3:4": (896, 1152), "3:2": (1216, 832), "2:3": (832, 1216)}


def _reason(exc: Exception) -> str:
    text = str(exc)
    if "401" in text or "403" in text:
        return "your Hugging Face token is not allowed to call Inference Providers"
    if "402" in text:
        return "your Hugging Face account is out of inference credits"
    if "404" in text or "not supported" in text.lower():
        return "no provider runs this model right now — pick another in Models"
    return text[:200] or type(exc).__name__


def _finish(cid: str, user_id: Optional[str], text: str, media: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    from ..storage import add_message

    add_message(cid, "assistant", text, media, user_id=user_id)
    return {"conversation_id": cid, "text": text, "media": media}


async def generate_image_turn(*, cid: str, user_id: Optional[str], model: str, prompt: str,
                              negative: Optional[str] = None, aspect_ratio: str = "1:1") -> Dict[str, Any]:
    from huggingface_hub import InferenceClient
    from ..files import save_generated_media_as_asset

    repo = strip_prefix(model)
    secret = token(user_id)
    if not secret:
        return _finish(cid, user_id, NOT_LINKED, None)
    width, height = _SIZES.get(aspect_ratio or "1:1", _SIZES["1:1"])
    client = InferenceClient(provider="auto", token=secret, timeout=240)
    try:
        try:
            image = await asyncio.to_thread(client.text_to_image, prompt, model=repo,
                                            negative_prompt=negative or None, width=width, height=height)
        except Exception:  # noqa: BLE001 — some providers refuse explicit sizes; try their default
            image = await asyncio.to_thread(client.text_to_image, prompt, model=repo)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
    except Exception as exc:  # noqa: BLE001
        return _finish(cid, user_id, f"Hugging Face couldn't make that image: {_reason(exc)}.", None)
    asset = save_generated_media_as_asset(user_id or "", buf.getvalue(), "image/png", "image", conversation_id=cid)
    media = {"images": [asset["url"]], "final_prompt": prompt, "model": f"{PREFIX}{repo}",
             "provider": ID, "width": image.width, "height": image.height}
    return _finish(cid, user_id, "Here you go.", media)


async def generate_video_turn(*, cid: str, user_id: Optional[str], model: str, prompt: str,
                              image_url: str = "", upload_path=None) -> Dict[str, Any]:
    from huggingface_hub import InferenceClient
    from ..files import save_generated_media_as_asset

    repo = strip_prefix(model)
    secret = token(user_id)
    if not secret:
        return _finish(cid, user_id, NOT_LINKED, None)
    client = InferenceClient(provider="auto", token=secret, timeout=600)
    try:
        if image_url and upload_path is not None:
            from ..multimodal import _load_image_bytes

            raw, _mime = await _load_image_bytes(image_url, upload_path)
            video = await asyncio.to_thread(client.image_to_video, raw, model=repo, prompt=prompt or None)
        else:
            video = await asyncio.to_thread(client.text_to_video, prompt, model=repo)
    except Exception as exc:  # noqa: BLE001
        return _finish(cid, user_id, f"Hugging Face couldn't make that video: {_reason(exc)}.", None)
    asset = save_generated_media_as_asset(user_id or "", video, "video/mp4", "video", conversation_id=cid)
    media = {"video_url": asset["url"], "final_prompt": prompt, "model": f"{PREFIX}{repo}", "provider": ID}
    return _finish(cid, user_id, "Here's your video.", media)
