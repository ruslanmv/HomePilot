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
rejected token is said plainly, never retried with someone else's user token.

On the hosted web edition (a Hugging Face Space) Hugging Face is the default engine for
everything, so the Space always has inference:
  * a visitor's own linked account is used first; else the Space's own token
    (``HOMEPILOT_HF_TOKEN``, or ``HF_TOKEN``, set as a Space secret) — never on a local install;
  * each type has a chain of default models (``HF_DEFAULT_*_MODELS``); a model that is down or
    unknown to the providers falls through to the next;
  * chat falls back to the local Ollama model when Hugging Face cannot answer at all (no token,
    out of credits, rate limited, unreachable) — see ``llm.chat``;
  * images and video go to Hugging Face whenever ComfyUI is not configured (``route_image``,
    ``route_video``) instead of failing with "set up ComfyUI".
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from . import store
from .context import current_user_id

logger = logging.getLogger("homepilot.connectors.huggingface")

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

# Default models per type, tried in order. Chosen from what Inference Providers serve; each
# list is overridable (comma-separated repo ids) without a code change.
_DEFAULTS = {
    "chat": ("HF_DEFAULT_CHAT_MODELS", "meta-llama/Llama-3.1-8B-Instruct,openai/gpt-oss-20b"),
    "multimodal": ("HF_DEFAULT_VISION_MODELS", "google/gemma-4-31B-it,Qwen/Qwen3.6-35B-A3B"),
    "image": ("HF_DEFAULT_IMAGE_MODELS", "black-forest-labs/FLUX.1-schnell,stabilityai/stable-diffusion-xl-base-1.0"),
    "video": ("HF_DEFAULT_VIDEO_MODELS", "Wan-AI/Wan2.2-TI2V-5B,Wan-AI/Wan2.1-T2V-1.3B"),
}
# How many models one request may try before giving up (keeps a failing turn short).
MAX_MODELS_PER_REQUEST = 2


def defaults(task: str) -> List[str]:
    env, fallback = _DEFAULTS[task]
    return [m.strip() for m in (os.getenv(env) or fallback).split(",") if m.strip()]


def is_web() -> bool:
    from ..config import HOMEPILOT_EDITION
    return HOMEPILOT_EDITION == "web"


def shared_token() -> str:
    """The Space's own token, for visitors without a linked account. Web edition only."""
    if not is_web():
        return ""
    return (os.getenv("HOMEPILOT_HF_TOKEN") or os.getenv("HF_TOKEN") or "").strip()


def comfy_configured() -> bool:
    from ..config import COMFY_BASE_URL
    return bool((COMFY_BASE_URL or "").strip())


def chain(task: str, chosen: str = "") -> List[str]:
    """The models to try for one request: the chosen one (if it is a Hub repo), then the
    defaults, without repeats, at most MAX_MODELS_PER_REQUEST."""
    repo = strip_prefix(chosen or "")
    out: List[str] = [repo] if "/" in repo else []
    for m in defaults(task):
        if m not in out:
            out.append(m)
    return out[:MAX_MODELS_PER_REQUEST]


def account_problem(exc: BaseException) -> bool:
    """A failure no other model would fix: the token is refused, out of credits, or rate
    limited. Trying the next model would only fail the same way and cost time."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 402, 403, 429):
        return True
    text = str(exc)
    return any(code in text for code in ("401", "402", "403", "429")) or isinstance(exc, NotLinked)

_cache: Dict[str, Any] = {}
_CACHE_S = 1800


class NotLinked(RuntimeError):
    pass


def token(user_id: Optional[str] = None) -> str:
    """The user's linked token, else (web edition only) the Space's own."""
    return store.secret(user_id or current_user_id(), ID) or shared_token()


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

# Hub queries that make up the candidate pool, the same three FitLab's inference lane uses: most
# liked, trending, newest — so a new model with few likes is still a candidate.
HUB_MODELS = "https://huggingface.co/api/models"
_EXPAND = ("likes", "downloads", "trendingScore", "lastModified", "createdAt", "tags",
           "library_name", "pipeline_tag", "inferenceProviderMapping")
_QUERIES = (("likes", 100), ("trendingScore", 100), ("createdAt", 60))
#: HomePilot's model types → FitLab inference-lane kinds.
_LANE_KIND = {"chat": "chat", "multimodal": "vision", "image": "image", "video": "video"}
ORDERS = ("popular", "likes", "trending", "newest", "rising")


def _list(task: str, secret: str) -> List[Dict[str, Any]]:
    """The raw candidate pool for ``task`` from the Hub (one row per repo), as the Hub returns it."""
    import httpx

    headers = {"User-Agent": "homepilot-model-ranking"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    pool: Dict[str, Dict[str, Any]] = {}
    errors = 0
    with httpx.Client(timeout=15.0, headers=headers) as client:
        for sort, limit in _QUERIES:
            params = [("pipeline_tag", TASKS[task]), ("inference_provider", "all"), ("sort", sort),
                      ("limit", str(limit))] + [("expand[]", e) for e in _EXPAND]
            try:
                r = client.get(HUB_MODELS, params=params)
                r.raise_for_status()
                for m in r.json():
                    pool.setdefault(m.get("id") or m.get("modelId") or "", m)
            except Exception as exc:  # noqa: BLE001 — one query down is not the whole list
                errors += 1
                logger.warning("Hugging Face model list (%s, %s) failed: %s", task, sort, str(exc)[:160])
    if errors == len(_QUERIES):
        raise RuntimeError("the Hugging Face Hub could not be reached")
    return [m for k, m in pool.items() if k]


def _row(task: str, ranked: Dict[str, Any]) -> Dict[str, Any]:
    """A ranked row as Models shows it: image/video ids carry ``hf:``; raw counts kept."""
    repo = ranked["id"]
    return {**ranked, "id": f"{PREFIX}{repo}" if task in ("image", "video") else repo, "name": repo}


def _from_fitlab(task: str, order: str) -> Tuple[List[Dict[str, Any]], str]:
    """FitLab's published ranking: the last copy fetched, else the one shipped with HomePilot."""
    from ..model_advisor import feed

    lane = feed.load("inference")
    k = ((lane.doc or {}).get("kinds") or {}).get(_LANE_KIND[task]) or {}
    rows = (k.get("lists") or {}).get(order) or (k.get("lists") or {}).get("popular") or []
    return [_row(task, r) for r in rows if isinstance(r, dict) and r.get("id")], f"fitlab-{lane.source}"


async def ranked(task: str, order: str = "popular") -> Tuple[List[Dict[str, Any]], str]:
    """Models Inference Providers serve live for ``task``, in ``order``, and where they came from.

    Live from the Hub, ranked with FitLab's inference-lane rules (model_advisor/inference.py):
    only models a provider serves live for the task HomePilot calls, adapters excluded; orders
    popular (likes, downloads, trend, freshness), likes, trending, newest, rising. The pool is
    cached for half an hour. When the Hub cannot be reached, FitLab's published ranking stands in.
    """
    from ..model_advisor import inference as lane

    if task not in TASKS:
        raise ValueError(f"Unknown model type '{task}'. Use one of: {', '.join(TASKS)}.")
    if order not in ORDERS:
        raise ValueError(f"Unknown order '{order}'. Use one of: {', '.join(ORDERS)}.")
    hit = _cache.get(task)
    pool = hit[1] if hit and time.time() - hit[0] < _CACHE_S else None
    if pool is None:
        try:
            pool = await asyncio.to_thread(_list, task, token())
            _cache[task] = (time.time(), pool)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ranking %s from FitLab's feed: %s", task, str(exc)[:160])
            return _from_fitlab(task, order)
    rows = lane.rank(pool, _LANE_KIND[task], order, limit=40)
    if not rows:
        return _from_fitlab(task, order)
    return [_row(task, r) for r in rows], "live"


async def models(task: str, order: str = "popular") -> List[Dict[str, Any]]:
    """Ranked models for ``task`` (see :func:`ranked`), without the source."""
    rows, _source = await ranked(task, order)
    return rows


# ── chat and vision ──────────────────────────────────────────────────────────

async def chat(messages: List[Dict[str, Any]], *, model: Optional[str], temperature: float, max_tokens: int) -> Dict[str, Any]:
    """Chat through the router: the chosen model, then the next default when it is down.
    Raises when Hugging Face cannot answer at all — ``llm.chat`` then uses Ollama."""
    from ..llm import chat_openai_compat

    secret = require_token()
    last: Optional[BaseException] = None
    for repo in chain("chat", model or ""):
        try:
            out = await chat_openai_compat(
                messages, temperature=temperature, max_tokens=max_tokens,
                base_url=ROUTER, model=repo, api_key=secret,
            )
            if isinstance(out, dict):
                out.setdefault("model", repo)   # which model of the chain answered
            return out
        except Exception as exc:  # noqa: BLE001
            last = exc
            logger.warning("Hugging Face chat with %s failed: %s", repo, str(exc)[:200])
            if account_problem(exc):
                break
    raise last or NotLinked(NOT_LINKED)


async def analyze_image(image_url: str, upload_path, **kwargs: Any) -> Dict[str, Any]:
    from ..multimodal import analyze_image_openai_compat

    t = token()
    if not t:
        return {"ok": False, "error": NOT_LINKED, "analysis_text": ""}
    kwargs.pop("api_key", None)
    kwargs.pop("base_url", None)
    chosen = kwargs.pop("model", None) or ""
    result: Dict[str, Any] = {"ok": False, "error": "No Hugging Face vision model answered.", "analysis_text": ""}
    for repo in chain("multimodal", chosen):
        result = await analyze_image_openai_compat(image_url, upload_path, base_url=ROUTER, api_key=t, model=repo, **kwargs)
        if result.get("ok"):
            return result
        logger.warning("Hugging Face vision with %s failed: %s", repo, str(result.get("error"))[:200])
    return result


# ── routing: when images and video go to Hugging Face ────────────────────────

def route_image(img_model: Optional[str]) -> Optional[str]:
    """The Hugging Face model for this image request, or None for ComfyUI. A model picked
    from Hugging Face always goes there; on the web edition without ComfyUI, so does
    everything else, instead of failing with "set up ComfyUI"."""
    if (img_model or "").startswith(PREFIX):
        return img_model
    if is_web() and not comfy_configured():
        return PREFIX + defaults("image")[0]
    return None


def route_video(vid_model: Optional[str]) -> Optional[str]:
    if (vid_model or "").startswith(PREFIX):
        return vid_model
    if is_web() and not comfy_configured():
        return PREFIX + defaults("video")[0]
    return None


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

    secret = token(user_id)
    if not secret:
        return _finish(cid, user_id, NOT_LINKED, None)
    width, height = _SIZES.get(aspect_ratio or "1:1", _SIZES["1:1"])
    client = InferenceClient(provider="auto", token=secret, timeout=240)
    image, repo, last = None, strip_prefix(model), None
    for repo in chain("image", model):
        try:
            try:
                image = await asyncio.to_thread(client.text_to_image, prompt, model=repo,
                                                negative_prompt=negative or None, width=width, height=height)
            except Exception as exc:  # noqa: BLE001 — some providers refuse explicit sizes
                if account_problem(exc):
                    raise
                image = await asyncio.to_thread(client.text_to_image, prompt, model=repo)
            break
        except Exception as exc:  # noqa: BLE001
            last = exc
            logger.warning("Hugging Face image with %s failed: %s", repo, str(exc)[:200])
            if account_problem(exc):
                break
    if image is None:
        return _finish(cid, user_id, f"Hugging Face couldn't make that image: {_reason(last or RuntimeError('no model'))}.", None)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    asset = save_generated_media_as_asset(user_id or "", buf.getvalue(), "image/png", "image", conversation_id=cid)
    media = {"images": [asset["url"]], "final_prompt": prompt, "model": f"{PREFIX}{repo}",
             "provider": ID, "width": image.width, "height": image.height}
    return _finish(cid, user_id, "Here you go.", media)


async def generate_video_turn(*, cid: str, user_id: Optional[str], model: str, prompt: str,
                              image_url: str = "", upload_path=None) -> Dict[str, Any]:
    from huggingface_hub import InferenceClient
    from ..files import save_generated_media_as_asset

    secret = token(user_id)
    if not secret:
        return _finish(cid, user_id, NOT_LINKED, None)
    client = InferenceClient(provider="auto", token=secret, timeout=600)
    raw = None
    if image_url and upload_path is not None:
        from ..multimodal import _load_image_bytes

        raw, _mime = await _load_image_bytes(image_url, upload_path)
    video, repo, last = None, strip_prefix(model), None
    for repo in chain("video", model):
        try:
            if raw is not None:
                video = await asyncio.to_thread(client.image_to_video, raw, model=repo, prompt=prompt or None)
            else:
                video = await asyncio.to_thread(client.text_to_video, prompt, model=repo)
            break
        except Exception as exc:  # noqa: BLE001
            last = exc
            logger.warning("Hugging Face video with %s failed: %s", repo, str(exc)[:200])
            if account_problem(exc):
                break
    if video is None:
        return _finish(cid, user_id, f"Hugging Face couldn't make that video: {_reason(last or RuntimeError('no model'))}.", None)
    asset = save_generated_media_as_asset(user_id or "", video, "video/mp4", "video", conversation_id=cid)
    media = {"video_url": asset["url"], "final_prompt": prompt, "model": f"{PREFIX}{repo}", "provider": ID}
    return _finish(cid, user_id, "Here's your video.", media)
